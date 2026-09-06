"""Does any of this generalise beyond ETH/USDC?

Every headline so far rests on one asset pair, and really on two of its three
fee tiers. WBTC/ETH and USDC/USDT widen the test enormously — not because they
add two more pools, but because they span three orders of magnitude of variance:

| Pool | pair | expected annualised volatility |
|---|---|---|
| USDC/USDT 1bp | a peg | near zero |
| WBTC/ETH 30bp | a cross of two correlated majors | low |
| ETH/USDC 5/30/100bp | a major against the dollar | ~50% |

`sigma^2/8` holding across that range would be a far stronger statement than it
holding on one asset. Failing on the peg would be informative too: at near-zero
variance the diffusion term vanishes and whatever LVR remains is *not* what the
theory describes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.build.derived import available_months
from src.build.h3 import daily_lvr
from src.utils.config import REPO_ROOT, pools
from src.utils.stats import newey_west_ols

CACHE = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"


def build(force: bool = False) -> pd.DataFrame:
    if CACHE.exists() and not force:
        return pd.read_parquet(CACHE)
    frames = []
    for spec in pools("all"):
        months = available_months(spec)
        if not months:
            print(f"  {spec.id}: no derived months, skipping", flush=True)
            continue
        got = 0
        for y, m in months:
            try:
                frames.append(daily_lvr(spec, y, m))
                got += 1
            except Exception as exc:
                print(f"  {spec.id} {y}-{m:02d}: {type(exc).__name__} {str(exc)[:50]}",
                      flush=True)
        print(f"  {spec.id}: {got} months", flush=True)
    out = pd.concat(frames, ignore_index=True).sort_values(["pool", "day"])
    out.to_parquet(CACHE, index=False)
    return out


def main() -> int:
    df = build()
    print(f"\n{len(df):,} pool-days across {df.pool.nunique()} pools\n")

    print("=" * 92)
    print("VOLATILITY RANGE — the point of adding these pools")
    print("=" * 92)
    v = df.groupby("pool").agg(days=("sigma_annual", "size"),
                               median_sigma=("sigma_annual", "median"),
                               p5=("sigma_annual", lambda s: s.quantile(.05)),
                               p95=("sigma_annual", lambda s: s.quantile(.95)))
    v = v.sort_values("median_sigma")
    print(v.to_string(float_format=lambda x: f"{x:9.4f}"))
    lo, hi = v.median_sigma.min(), v.median_sigma.max()
    print(f"\n  spread in median volatility: {hi / lo:,.0f}x  "
          f"({lo:.2%} to {hi:.2%})")
    print(f"  in VARIANCE, which is what LVR scales with: {(hi / lo) ** 2:,.0f}x")

    print("\n" + "=" * 92)
    print("H3 PER POOL — does the closed form hold outside ETH/USDC?")
    print("=" * 92)
    rows = []
    for pid, g in df.groupby("pool", sort=False):
        g = g[(g.lvr_analytical_usd > 0) & g.lvr_empirical_usd.notna()]
        if len(g) < 60:
            print(f"  {pid}: only {len(g)} usable days, skipped")
            continue
        f = newey_west_ols(g.lvr_empirical_usd, g.lvr_analytical_usd)
        rows.append({"pool": pid, "fee_bps": int(g.fee_tier_bps.iloc[0]),
                     "median_sigma": g.sigma_annual.median(), "n": f.n_obs,
                     "beta": f.beta, "se": f.beta_se, "r2": f.r_squared,
                     "p_beta_eq_1": f.beta_equals(1.0),
                     "ratio": g.lvr_empirical_usd.sum() / g.lvr_analytical_usd.sum()})
    t = pd.DataFrame(rows).sort_values("median_sigma")
    print(t.to_string(index=False, float_format=lambda x: f"{x:9.4f}"))

    print("\n" + "=" * 92)
    print("LVR PER UNIT VARIANCE — the fee-tier claim, now across four tiers")
    print("=" * 92)
    slopes = []
    for pid, g in df.groupby("pool", sort=False):
        g = g.copy()
        g["var"] = g.sigma_annual.astype(float) ** 2
        g["lvr_norm"] = g.lvr_empirical_usd / g.value_usd
        g = g[(g["var"] > 0) & g.lvr_norm.notna() & np.isfinite(g.lvr_norm)]
        if len(g) < 60:
            continue
        f = newey_west_ols(g.lvr_norm, g["var"])
        slopes.append({"pool": pid, "fee_bps": int(g.fee_tier_bps.iloc[0]),
                       "n": f.n_obs, "slope": f.beta, "se": f.beta_se, "r2": f.r_squared})
    s = pd.DataFrame(slopes).sort_values("fee_bps")
    print(s.to_string(index=False, float_format=lambda x: f"{x:11.5f}"))
    if len(s) > 1:
        print(f"\n  fee tiers spanned: {s.fee_bps.min()}bp to {s.fee_bps.max()}bp "
              f"({s.fee_bps.max() / s.fee_bps.min():.0f}x)")
        print(f"  slope range: {s.slope.min():.5f} to {s.slope.max():.5f} "
              f"({s.slope.max() / s.slope.min():.2f}x)")

    out = REPO_ROOT / "outputs" / "tables"
    t.to_csv(out / "cross_section_h3.csv", index=False)
    s.to_csv(out / "cross_section_lvr_slopes.csv", index=False)
    v.to_csv(out / "cross_section_volatility.csv")
    print(f"\nwrote cross_section_h3.csv, cross_section_lvr_slopes.csv, "
          f"cross_section_volatility.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
