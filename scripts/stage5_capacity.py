"""ETH/USDC 100bp at a notional it can actually support.

A $100k position holds a median 113% of that pool's active liquidity — more than
the entire pool. It is not a price-taker, the fee-share model does not apply, and
the position would move the price it is being measured against. Both the
uncorrected (+34.65%) and corrected (-43.10%) figures at that size are artefacts.

This sweeps notional down until the position is small relative to the pool, and
reports where the answer stabilises.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months, load_derived, month_bounds
from src.build.recentre import simulate_recentred
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool
from src.utils.stats import block_bootstrap_ci

NOTIONALS = [Decimal(n) for n in ("1000", "2000", "5000", "10000", "25000", "100000")]
GAS = Decimal("22.39")


def main() -> int:
    spec = pool("ETH_USDC_100bp")
    bounds = month_bounds()
    months = available_months(spec)
    rows = []

    for notional in NOTIONALS:
        nets, shares = [], []
        for y, m in months:
            k0, k1 = f"{y:04d}-{m:02d}", (f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}")
            if k0 not in bounds or k1 not in bounds:
                continue
            d = load_derived(spec, [(y, m)])
            if len(d) < 50:
                continue
            sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
            r = simulate_recentred(d, sw, spec, notional, Decimal("0.10"),
                                   d["rv_annualised"], GAS, GAS)
            nets.append(float(r.net))
            shares.append(r.median_liquidity_share)
        s = pd.Series(nets)
        share = pd.Series(shares).median()
        try:
            lo, hi = block_bootstrap_ci(s, block_size=6, n_boot=2000)
        except Exception:
            lo = hi = float("nan")
        rows.append({"notional": float(notional), "median_liquidity_share": share,
                     "n_cohorts": len(s), "mean_net": s.mean(), "median_net": s.median(),
                     "ci_low": lo, "ci_high": hi, "price_taker": share < 0.02})
        print(f"  ${float(notional):>8,.0f}  L share {share:7.2%}  net {s.mean():+8.2%}  "
              f"CI [{lo:+.1%}, {hi:+.1%}]  {'price-taker' if share < 0.02 else 'TOO LARGE'}",
              flush=True)

    t = pd.DataFrame(rows)
    out = REPO_ROOT / "outputs" / "tables"
    t.to_csv(out / "capacity_sweep_100bp.csv", index=False)
    valid = t[t.price_taker]
    print("\nThe answer only means anything where the position is a price-taker.")
    if len(valid):
        v = valid.iloc[-1]
        print(f"Largest valid size: ${v.notional:,.0f} (L share {v.median_liquidity_share:.2%}), "
              f"net {v.mean_net:+.2%}, CI [{v.ci_low:+.1%}, {v.ci_high:+.1%}]")
    print("\nwrote outputs/tables/capacity_sweep_100bp.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
