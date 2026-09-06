"""Robustness — sensitivity of the MEV result to the classification rule.

Stage 4.3 requires this. Sandwich detection is heuristic and the plan says so;
the honest response is to show how much the answer moves across the rule's
parameters rather than to defend one setting.

Three parameters, swept independently around the baseline:
- **reversal tolerance** — how exactly the back leg must unwind the front
- **leg span** — how far apart the two legs may sit within a block
- **profit filter** — whether loss-making candidates count
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months, month_bounds
from src.build.mev import (classify_sandwiches_by_address, sandwich_intensity,
                           sandwich_profit_usd)
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool
from src.utils.speclog import log_specification

POOL = "ETH_USDC_5bp"          # the only pool with material sandwich activity
TOLERANCES = [0.02, 0.05, 0.10, 0.25, 0.50, 1.00]
SPANS = [2, 3, 4, 8, 24, 64]


def main() -> int:
    spec = pool(POOL)
    bounds = month_bounds()
    months = available_months(spec)

    cache = {}
    for y, m in months:
        k0 = f"{y:04d}-{m:02d}"
        k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
        if k0 not in bounds or k1 not in bounds:
            continue
        cache[k0] = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
    print(f"{POOL}: {sum(len(v) for v in cache.values()):,} swaps across {len(cache)} months\n")

    def sweep(label, **kw):
        rows = []
        for k0, sw in cache.items():
            s = classify_sandwiches_by_address(sw, spec, **kw)
            i = sandwich_intensity(sw, s)
            profit = float(sandwich_profit_usd(s, spec, Decimal("2500")).map(float).sum()) if len(s) else 0.0
            rows.append({"month": k0, "n_sandwiches": len(s),
                         "attacker_swap_share": i["attacker_swap_share"],
                         "profit_usd": profit,
                         "neg_share": float((sandwich_profit_usd(s, spec, Decimal("2500")).map(float) < 0).mean()) if len(s) else 0.0})
        t = pd.DataFrame(rows)
        return {"rule": label, "n_sandwiches": int(t.n_sandwiches.sum()),
                "attacker_share": t.attacker_swap_share.mean(),
                "profit_usd": t.profit_usd.sum(),
                "loss_making_share": t.neg_share.mean()}

    print("--- reversal tolerance (span 24, profit filter on) ---")
    out = []
    for tol in TOLERANCES:
        r = sweep(f"reversal {tol:.0%}", reversal_tolerance=tol, max_leg_span=24,
                  require_positive_profit=True)
        out.append(r)
        print(f"  {r['rule']:16s} n={r['n_sandwiches']:6,}  share {r['attacker_share']:6.3%}  "
              f"profit ${r['profit_usd']:12,.0f}", flush=True)

    for meas in ("pool_position", "log_index"):
        print(f"\n--- leg span, measured in {meas} (reversal 10%, profit filter on) ---")
        for span in SPANS:
            r = sweep(f"span {span} ({meas})", reversal_tolerance=0.10, max_leg_span=span,
                      require_positive_profit=True, span_measure=meas)
            out.append(r)
            print(f"  {r['rule']:28s} n={r['n_sandwiches']:6,}  share {r['attacker_share']:6.3%}  "
                  f"profit ${r['profit_usd']:12,.0f}", flush=True)

    print("\n--- profit filter (reversal 10%, span 24) ---")
    for flag in (True, False):
        r = sweep(f"profit filter {'on' if flag else 'off'}", reversal_tolerance=0.10,
                  max_leg_span=24, require_positive_profit=flag)
        out.append(r)
        print(f"  {r['rule']:22s} n={r['n_sandwiches']:6,}  profit ${r['profit_usd']:12,.0f}  "
              f"loss-making {r['loss_making_share']:5.1%}", flush=True)

    t = pd.DataFrame(out)
    t_sat = t[t.rule.str.contains("pool_position", na=False)]
    base = t[t.rule == "reversal 10%"].iloc[0]
    t["n_vs_baseline"] = t.n_sandwiches / base.n_sandwiches
    t["profit_vs_baseline"] = t.profit_usd / base.profit_usd
    print(f"\n--- spread across every rule tested ---")
    print(f"  sandwich count : {t.n_sandwiches.min():,} to {t.n_sandwiches.max():,}  "
          f"({t.n_sandwiches.max() / max(1, t.n_sandwiches.min()):.1f}x)")
    print(f"  attacker profit: ${t.profit_usd.min():,.0f} to ${t.profit_usd.max():,.0f}  "
          f"({t.profit_usd.max() / max(1, t.profit_usd.min()):.1f}x)")
    if len(t_sat):
        print(f"\n--- restricted to the correct span measure (pool_position) ---")
        print(f"  sandwich count : {t_sat.n_sandwiches.min():,} to {t_sat.n_sandwiches.max():,}  "
              f"({t_sat.n_sandwiches.max() / max(1, t_sat.n_sandwiches.min()):.2f}x)")
        print(f"  attacker profit: ${t_sat.profit_usd.min():,.0f} to "
              f"${t_sat.profit_usd.max():,.0f}  "
              f"({t_sat.profit_usd.max() / max(1, t_sat.profit_usd.min()):.2f}x)")
    print(f"\n  Attribution is `neutral` (DECISIONS 4.2), so the LP-side cost is zero")
    print(f"  under every rule here. The sensitivity matters for the MEV *intensity*")
    print(f"  covariate in the forecast model, not for the decomposition table.")

    t.to_csv(REPO_ROOT / "outputs" / "tables" / "robustness_mev.csv", index=False)
    log_specification(stage="R", component="mev_rule_sweep",
                      params={"tolerances": TOLERANCES, "spans": SPANS},
                      metric_name="n_rules", metric_value=len(t))
    print(f"\nwrote outputs/tables/robustness_mev.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
