"""Does the static rule survive scrutiny? — step 3.

"Always hold the lowest-sigma pool" earns +6.4% at Sharpe 1.96 and is the
paper's only actionable recommendation. It scores 0.83 against a 0.95 deflated-
Sharpe bar, so it is currently *suggestive*. This asks the three questions that
decide whether it can be recommended at all.

**1. Sharpe against what?** `src/utils/stats.py` computes `mean/sd` with no
risk-free rate: the return is measured against zero, not against cash. But the
position ties up real capital, and over 2023-2026 T-bills paid several percent.
The FRED series could not be fetched from this machine, so rather than invent
one this reports a **sensitivity band** across plausible rates and lets the
reader put the cursor where they like.

**2. Is it "lowest sigma", or is it "the peg"?** The rule is stated in terms of
volatility, but it has only ever selected one pool. If it is really a statement
about volatility it should also work applied to the *second* lowest, and the
sigma ordering should keep predicting. Step 2 already found the cross-pool
sigma-net link does not reproduce within pools, so this is the sharper test.

**3. Does it hold out of sample?** Split by period. A rule that earns its Sharpe
in one regime and gives it back in another is a regime bet, not a rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT
from src.utils.speclog import count_specifications
from src.utils.stats import deflated_sharpe_ratio

PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel_all.parquet"
OUT = REPO_ROOT / "outputs" / "tables"
EXCLUDE = "ETH_USDC_100bp"
GAS_WEEK = 22.39 / 100_000
#: Plausible cash rates over 2023-2026. The exact path could not be fetched, so
#: the honest presentation is a band rather than a single deflated number.
RF_GRID = (0.00, 0.02, 0.04, 0.05)


def weekly(panel: pd.DataFrame) -> pd.DataFrame:
    d = panel[panel.pool != EXCLUDE].copy()
    d = d.dropna(subset=["net_return", "realized_vol_30d"])
    return d.sort_values(["week", "pool"])


def series_for(d: pd.DataFrame, rank: int) -> pd.Series:
    """Weekly return of holding the `rank`-th lowest-sigma pool each week.

    Volatility is lagged: the choice for a week uses the 30-day realised vol
    known *before* it, or the rule would be unimplementable.
    """
    d = d.copy()
    d["vol_lag"] = d.groupby("pool")["realized_vol_30d"].shift(1)
    out = {}
    for wk, g in d.dropna(subset=["vol_lag"]).groupby("week"):
        g = g.sort_values("vol_lag")
        if len(g) > rank:
            out[wk] = g["net_return"].to_numpy()[rank] - GAS_WEEK
    return pd.Series(out).sort_index()


def score(r: pd.Series, n_trials: int, rf: float = 0.0) -> dict:
    ex = r - rf / 52
    d = deflated_sharpe_ratio(ex, n_trials=n_trials)
    return {"ann_return": float(r.mean() * 52), "vol": float(r.std(ddof=1) * np.sqrt(52)),
            "sharpe": d["sharpe"], "deflated_prob": d["deflated_sharpe_prob"],
            "n": len(r)}


def main() -> int:
    d = weekly(pd.read_parquet(PANEL))
    n_trials = max(count_specifications(), 1)
    print("=" * 84)
    print("STEP 3 — can the static rule be recommended?")
    print("=" * 84)
    print(f"\n{d.pool.nunique()} pools, {d.week.nunique()} weeks, "
          f"{n_trials} specifications logged\n")

    # ---- 1. the risk-free question --------------------------------------
    rule = series_for(d, 0)
    print(f"--- 1. Sharpe against cash, not against zero ({len(rule)} weeks) ---\n")
    print(f"{'rf':>6} {'excess ann':>12} {'sharpe':>9} {'deflated p':>12}  verdict")
    rows = []
    for rf in RF_GRID:
        s = score(rule, n_trials, rf)
        ex_ann = s["ann_return"] - rf
        verdict = "clears 0.95" if s["deflated_prob"] >= 0.95 else "fails"
        print(f"{rf:6.1%} {ex_ann:+12.2%} {s['sharpe']:9.2f} "
              f"{s['deflated_prob']:12.3f}  {verdict}")
        rows.append({"test": "risk_free_sensitivity", "rf": rf,
                     "excess_ann": ex_ann, "sharpe": s["sharpe"],
                     "deflated_prob": s["deflated_prob"]})
    print("\n  The reported +6.4% at Sharpe 1.96 is the rf = 0 row. Cash is the"
          "\n  honest alternative for capital that is actually tied up.")

    # ---- 2. is it sigma, or is it the peg? -------------------------------
    print("\n--- 2. is the rule about volatility, or about one pool? ---\n")
    print(f"{'rank by lagged sigma':>22} {'ann':>9} {'sharpe':>8} {'deflated p':>12}"
          f" {'modal pool':>16}")
    dd = d.copy()
    dd["vol_lag"] = dd.groupby("pool")["realized_vol_30d"].shift(1)
    for rank in range(4):
        r = series_for(d, rank)
        if len(r) < 10:
            continue
        s = score(r, n_trials)
        modal = (dd.dropna(subset=["vol_lag"]).sort_values("vol_lag")
                   .groupby("week").nth(rank)["pool"].mode())
        modal = modal.iloc[0] if len(modal) else "-"
        print(f"{rank + 1:>22} {s['ann_return']:+9.2%} {s['sharpe']:8.2f} "
              f"{s['deflated_prob']:12.3f} {modal:>16}")
        rows.append({"test": "rank_ladder", "rank": rank + 1,
                     "ann": s["ann_return"], "sharpe": s["sharpe"],
                     "deflated_prob": s["deflated_prob"], "modal_pool": modal})
    print("\n  If the rule encoded a volatility mechanism, performance should"
          "\n  decay smoothly down the ladder. Read the second row against the"
          "\n  first before calling this a volatility rule.")

    # ---- 3. does it hold across periods? --------------------------------
    print("\n--- 3. stability across periods (rule = rank 1, rf = 0) ---\n")
    yr = rule.groupby(pd.DatetimeIndex(rule.index).year)
    print(f"{'year':>6} {'weeks':>6} {'ann':>9} {'sharpe':>8} {'share +ve':>10}")
    for y, r in yr:
        if len(r) < 8:
            continue
        sh = r.mean() / r.std(ddof=1) * np.sqrt(52) if r.std(ddof=1) > 0 else np.nan
        print(f"{y:>6} {len(r):>6} {r.mean() * 52:+9.2%} {sh:8.2f} "
              f"{(r > 0).mean():10.1%}")
        rows.append({"test": "by_year", "year": int(y), "weeks": len(r),
                     "ann": float(r.mean() * 52), "sharpe": float(sh),
                     "share_positive": float((r > 0).mean())})

    half = len(rule) // 2
    for label, r in (("first half", rule.iloc[:half]), ("second half", rule.iloc[half:])):
        s = score(r, n_trials)
        print(f"\n  {label:12s} ann {s['ann_return']:+.2%}  sharpe {s['sharpe']:.2f}"
              f"  deflated p {s['deflated_prob']:.3f}")
        rows.append({"test": "split_half", "label": label, "ann": s["ann_return"],
                     "sharpe": s["sharpe"], "deflated_prob": s["deflated_prob"]})

    pd.DataFrame(rows).to_csv(OUT / "static_rule.csv", index=False)
    print("\nwrote outputs/tables/static_rule.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
