"""Stage 5 across the full sample — the headline decomposition.

One monthly cohort per pool per month: open a $100k position at +/-10%, re-centre
on range exit, hold to month end. Both variants reported — delta-hedged leads,
raw is the robustness column.

Monthly cohorts matter. A single entry date makes the headline an artefact of
that date: a position opened 1 January 2023 was run over by a 40% rally in its
second week, and one opened three weeks later was not.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months, load_derived, month_bounds
from src.build.hedge import simulate_hedge_on_path
from src.build.recentre import simulate_recentred
from src.fetch.binance_data import load_funding_rates, load_perp_klines_1m
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pools
from src.utils.speclog import log_specification
from src.utils.stats import block_bootstrap_ci

NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")
GAS_RECENTRE = GAS_ENTRY_EXIT = Decimal("22.39")
HEDGE_FREQ = 3600          # hourly, per the revised Stage 0.1 baseline


def run_cohort(spec, year: int, month: int, bounds: dict) -> dict | None:
    k0 = f"{year:04d}-{month:02d}"
    ky, km = (year + 1, 1) if month == 12 else (year, month + 1)
    k1 = f"{ky:04d}-{km:02d}"
    if k0 not in bounds or k1 not in bounds:
        return None

    d = load_derived(spec, [(year, month)])
    if len(d) < 50:
        return None
    sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))

    r = simulate_recentred(d, sw, spec, NOTIONAL, HALF_WIDTH, d["rv_annualised"],
                           GAS_RECENTRE, GAS_ENTRY_EXIT)

    row = {
        "pool": spec.id, "fee_tier_bps": spec.fee_tier_bps, "year": year, "month": month,
        "days": float(r.days), "n_recentres": r.n_recentres,
        "share_in_range": float(r.share_in_range),
        "realised_delta": r.realised_half_width_log,
        "median_liquidity_share": r.median_liquidity_share,
        "fees": float(r.fees), "lvr": float(r.lvr_cex_path),
        "lvr_analytical": float(r.lvr_analytical), "gas": float(r.gas),
        "net_raw": float(r.net),
    }

    try:
        perp = load_perp_klines_1m("ETHUSDT", year, month)
        fund = load_funding_rates("ETHUSDT", year, month)
        h = simulate_hedge_on_path(r.delta_path, perp, fund, HEDGE_FREQ, base_usd=NOTIONAL)
        row.update({
            "funding": float(h.funding), "hedge_trading_cost": float(h.trading_cost),
            "hedge_pnl": float(h.pnl),
            "hedge_error_usd": float(h.mean_abs_error_usd),
            "net_hedged": float(r.net) - float(h.funding) - float(h.trading_cost),
        })
    except Exception as exc:
        row.update({"funding": None, "hedge_trading_cost": None, "hedge_pnl": None,
                    "hedge_error_usd": None, "net_hedged": None,
                    "hedge_note": f"{type(exc).__name__}: {str(exc)[:60]}"})
    return row


def main() -> int:
    bounds = month_bounds()
    rows = []
    for spec in pools("core"):
        months = available_months(spec)
        print(f"\n=== {spec.id}: {len(months)} cohorts ===", flush=True)
        for y, m in months:
            try:
                r = run_cohort(spec, y, m, bounds)
                if r:
                    rows.append(r)
                    print(f"  {y}-{m:02d}  in-range {r['share_in_range']:5.1%}  "
                          f"fees {r['fees']:+8.2%}  lvr {r['lvr']:+8.2%}  "
                          f"net_raw {r['net_raw']:+8.2%}  "
                          f"net_hedged {(f'{r['net_hedged']:+8.2%}' if r['net_hedged'] is not None else '     n/a')}",
                          flush=True)
            except Exception as exc:
                print(f"  {y}-{m:02d}: FAILED {type(exc).__name__} {str(exc)[:70]}", flush=True)

    t = pd.DataFrame(rows)
    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "cohorts_fullsample.csv", index=False)

    log_specification(
        stage="5", component="decomposition_fullsample",
        params={"notional": float(NOTIONAL), "half_width": float(HALF_WIDTH),
                "recentre": "on_range_exit", "hedge_freq_s": HEDGE_FREQ,
                "cohorts": "monthly"},
        metric_name="n_cohorts", metric_value=len(t),
        notes="full-sample Stage 5, both variants",
    )

    print("\n\n=== Output 1: full sample, monthly cohorts, $100k at +/-10% ===\n")
    agg = []
    for pid, g in t.groupby("pool", sort=False):
        row = {"pool": pid, "fee_tier_bps": int(g.fee_tier_bps.iloc[0]), "n_cohorts": len(g)}
        for col in ("share_in_range", "fees", "lvr", "gas", "net_raw"):
            row[col] = g[col].mean()
        hg = g.dropna(subset=["net_hedged"])
        row["funding"] = hg["funding"].mean() if len(hg) else float("nan")
        row["net_hedged"] = hg["net_hedged"].mean() if len(hg) else float("nan")
        try:
            lo, hi = block_bootstrap_ci(g["net_raw"], block_size=6, n_boot=2000)
            row["net_raw_ci"] = f"[{lo:+.1%}, {hi:+.1%}]"
        except Exception:
            row["net_raw_ci"] = "n/a"
        try:
            lo, hi = block_bootstrap_ci(hg["net_hedged"], block_size=6, n_boot=2000)
            row["net_hedged_ci"] = f"[{lo:+.1%}, {hi:+.1%}]"
        except Exception:
            row["net_hedged_ci"] = "n/a"
        row["share_of_months_positive"] = float((g["net_raw"] > 0).mean())
        agg.append(row)

    a = pd.DataFrame(agg)
    show = a.copy()
    for c in ("share_in_range", "fees", "lvr", "gas", "net_raw", "funding", "net_hedged",
              "share_of_months_positive"):
        show[c] = show[c].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "n/a")
    print(show.to_string(index=False))
    a.to_csv(out / "decomposition_fullsample.csv", index=False)
    print(f"\nwrote outputs/tables/decomposition_fullsample.csv and cohorts_fullsample.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
