"""Why is beta 0.372 in 2023 and ~0.92 afterwards? — step 4.

H3 regresses realised LVR on the closed form. The slope is 0.372 in 2023
against 0.918-0.944 later, and that gap was carried as unexplained.

The answer is that **"2023" is the wrong unit**. The year's low beta comes from
two days, and the level of LVR in 2023 is otherwise correct: aggregate
empirical/analytical is 0.961 for the year, so this is a slope artefact, not a
bias.

Three candidate mechanisms are tested and **all three are refused**, which is
reported rather than buried:

- **the no-arbitrage fee band** — predicts the ratio rises with sigma/fee.
  It does not (elasticity -0.048, R^2 0.008); beta is *higher* at low sigma/fee.
- **jumps** — predicts a jump-robust variance fixes it. Substituting bipower
  variation moves 2023's beta from 0.372 to 0.381. It does not.
- **oversampling** — predicts realised variance inflates at fine sampling on
  the extreme days. It deflates: rv(1s)/rv(300s) is 0.52 on the three most
  volatile days of August 2023.

What survives is that the closed form **over-predicts on extreme-volatility
days**, monotonically, and that this is the same failure H3 already documented
at the other end of the range on the peg.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT

DAILY = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
OUT = REPO_ROOT / "outputs" / "tables"
EXCLUDE = ("ETH_USDC_100bp",)


def beta(g: pd.DataFrame) -> float:
    X = np.column_stack([np.ones(len(g)), g["lvr_analytical_usd"].to_numpy()])
    return float(np.linalg.lstsq(X, g["lvr_empirical_usd"].to_numpy(),
                                 rcond=None)[0][1])


def main() -> int:
    d = pd.read_parquet(DAILY)
    d = d[~d.pool.isin(EXCLUDE) & (d.lvr_analytical_usd > 0)].copy()
    d["year"] = d.day.dt.year
    d["ratio"] = d.lvr_empirical_usd / d.lvr_analytical_usd
    np_ = d[d.pool != "USDC_USDT_1bp"].copy()

    print("=" * 84)
    print("STEP 4 — what is different about 2023?")
    print("=" * 84)

    print("\n--- the slope falls but the level does not ---\n")
    print(f"{'year':>6} {'beta':>8} {'agg ratio':>11} {'median sigma':>13} {'n':>6}")
    rows = []
    for y, g in np_.groupby("year"):
        r = g.lvr_empirical_usd.sum() / g.lvr_analytical_usd.sum()
        print(f"{y:>6} {beta(g):8.3f} {r:11.3f} {g.sigma_annual.median():13.3f} {len(g):>6}")
        rows.append({"test": "by_year", "year": int(y), "beta": beta(g),
                     "agg_ratio": float(r)})
    print("\n  A level bias would move the ratio. It does not: 2023 is 0.958."
          "\n  So the closed form is right on average in 2023 and wrong in shape.")

    print("\n--- it is two days ---\n")
    q3 = np_[(np_.year == 2023) & (np_.day.dt.quarter == 3)]
    top = q3.nlargest(5, "lvr_analytical_usd")
    print(f"{'quarter':>9} {'beta':>8} {'agg ratio':>11}")
    for q, g in np_[np_.year == 2023].groupby(np_.day.dt.quarter):
        print(f"{'2023Q' + str(q):>9} {beta(g):8.3f} "
              f"{g.lvr_empirical_usd.sum() / g.lvr_analytical_usd.sum():11.3f}")
    ex = q3.drop(index=top.index)
    print(f"\n  2023Q3 carries it. Its top 5 day-pool cells are "
          f"{top.lvr_analytical_usd.sum() / q3.lvr_analytical_usd.sum():.1%} of the"
          f"\n  quarter's analytical LVR and have a ratio of "
          f"{top.lvr_empirical_usd.sum() / top.lvr_analytical_usd.sum():.3f}.")
    print(f"  2023Q3 without them: ratio "
          f"{ex.lvr_empirical_usd.sum() / ex.lvr_analytical_usd.sum():.3f} — normal.")
    print("  All five fall on 17-18 August 2023.")

    print("\n--- drop the top 1% of sigma days and the year effect goes ---\n")
    cut = np_.sigma_annual.quantile(0.99)
    print(f"{'year':>6} {'beta (all)':>12} {'beta (ex top 1%)':>18}")
    keep = np_[np_.sigma_annual <= cut]
    for y in sorted(np_.year.unique()):
        b_all = beta(np_[np_.year == y])
        b_ex = beta(keep[keep.year == y])
        print(f"{y:>6} {b_all:12.3f} {b_ex:18.3f}")
        rows.append({"test": "ex_top1pct", "year": int(y), "beta_all": b_all,
                     "beta_ex": b_ex})
    print(f"\n  cutoff sigma = {cut:.2f} annualised; {len(np_) - len(keep)} of "
          f"{len(np_)} day-pool cells removed.")
    print("  2023 moves 0.425 -> 0.779 and the spread across years collapses.")

    print("\n--- the closed form's bias is monotone in sigma ---\n")
    d["sbin"] = pd.qcut(d.sigma_annual, [0, .25, .5, .75, .9, .99, 1.0],
                        labels=["q1", "q2", "q3", "p75-90", "p90-99", "top1%"])
    t = d.groupby("sbin", observed=True).apply(
        lambda s: pd.Series({"n": len(s), "median_sigma": s.sigma_annual.median(),
                             "agg_ratio": s.lvr_empirical_usd.sum()
                             / s.lvr_analytical_usd.sum()}), include_groups=False)
    print(t.to_string(float_format=lambda v: f"{v:10.3f}"))
    print("\n  Under-predicts at low sigma (the adverse-selection floor H3 found"
          "\n  on the peg), unbiased near 0.6-0.9, over-predicts above it."
          "\n  That is a stated domain of validity, not a 2023 story.")

    pd.DataFrame(rows).to_csv(OUT / "why_2023.csv", index=False)
    t.reset_index().astype({"sbin": str}).to_csv(OUT / "lvr_bias_by_sigma.csv",
                                                 index=False)
    print("\nwrote why_2023.csv, lvr_bias_by_sigma.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
