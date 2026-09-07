"""Two allocation regimes: may hold cash, or must be invested every week.

The distinction matters more than any modelling choice made so far. A mandate
that forces capital into a pool every week can only choose *which* pool; one
that may sit out can also choose *whether*. Separating them says where the
available edge actually lives, and puts a ceiling on each.

Each regime is run three ways: with perfect foresight (the ceiling), with the
Stage 6 forecast (what we achieved), and passively (the floor).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.model.forecast import fit_lightgbm
from src.model.purged_cv import PurgedKFold
from src.model.volatility import har_rv_forecast
from src.utils.config import REPO_ROOT
from src.utils.speclog import count_specifications
from src.utils.stats import deflated_sharpe_ratio

PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel.parquet"
DAILY = REPO_ROOT / "data" / "processed" / "h3_daily.parquet"
POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")
NOTIONAL, GAS_WEEK, WK = 100_000.0, 22.39 / 100_000, 52
FEE_FEATURES = ["fees_lag1", "fees_usd", "realized_vol_7d", "swaps_7d"]


def variance_series(pool: str) -> pd.DataFrame:
    d = pd.read_parquet(DAILY)
    d = d[d.pool == pool].copy()
    d.index = pd.to_datetime(d["day"], utc=True)
    rv = (d["sigma_annual"].astype(float) ** 2).sort_index()
    out = pd.DataFrame({"rv_now": rv.resample("W").mean(),
                        "rv_forecast": har_rv_forecast(rv, 7, 60).resample("W").last()})
    out["pool"] = pool
    return out.reset_index().rename(columns={out.index.name or "index": "week", "day": "week"})


def stats(r: pd.Series, name: str, n_trials: int) -> dict:
    r = pd.Series(r).dropna()
    ann, vol = r.mean() * WK, r.std(ddof=1) * np.sqrt(WK)
    c = (1 + r).cumprod()
    row = {"strategy": name, "ann_return": ann, "volatility": vol,
           "sharpe": ann / vol if vol else np.nan,
           "max_drawdown": float((c / c.cummax() - 1).min()),
           "total_return": float(c.iloc[-1] - 1),
           "weeks_positive": float((r > 0).mean())}
    try:
        d = deflated_sharpe_ratio(r, n_trials=n_trials, periods_per_year=WK)
        row["deflated_prob"] = d["deflated_sharpe_prob"]
        row["beats_null"] = d["beats_null"]
    except Exception:
        row["deflated_prob"], row["beats_null"] = np.nan, False
    return row


def main() -> int:
    panel = pd.read_parquet(PANEL)
    panel = panel[panel.pool.isin(POOLS)].copy()
    panel["target_fees_next"] = panel.groupby("pool")["fees_usd"].shift(-1)
    fc = pd.concat([variance_series(p) for p in POOLS], ignore_index=True)
    d = panel.merge(fc, on=["pool", "week"], how="left").dropna(
        subset=["target_net_next", "target_fees_next", "rv_now", "rv_forecast"]
        + FEE_FEATURES).sort_values("week").reset_index(drop=True)

    cv = PurgedKFold(n_splits=5, purge_days=7, embargo_days=7)
    X = d[FEE_FEATURES].astype(float)
    X.index = pd.DatetimeIndex(d["week"])
    y = pd.Series(d["target_fees_next"].astype(float).to_numpy(), index=X.index)
    fees = fit_lightgbm(X, y, cv, name="fees")
    d["pred_fees"] = fees.predictions.reindex(X.index).to_numpy() / NOTIONAL
    d["pred_lvr"] = (d["lvr_analytical_usd"].astype(float)
                     * (d["rv_forecast"].astype(float) / d["rv_now"].astype(float))) / NOTIONAL
    d["pred_net"] = d["pred_fees"] - d["pred_lvr"] - GAS_WEEK
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["pred_net"])

    realised = d.pivot_table(index="week", columns="pool", values="target_net_next")
    predicted = d.pivot_table(index="week", columns="pool", values="pred_net")
    common = realised.dropna().index.intersection(predicted.dropna().index)
    R, P = realised.loc[common], predicted.loc[common]
    n_trials = count_specifications()

    print(f"{len(R)} weeks, pools {list(R.columns)}, {n_trials} specifications logged\n")

    rows = []
    # ---------------- Regime A: may hold cash ---------------------------- #
    rows.append(stats(R.max(axis=1).clip(lower=0.0),
                      "A. FLEXIBLE — oracle (best pool, cash if all negative)", n_trials))
    pick = P.idxmax(axis=1)
    chosen = pd.Series([R.loc[w, pick[w]] for w in R.index], index=R.index)
    invest = pd.Series([P.loc[w, pick[w]] > 0 for w in R.index], index=R.index)
    rows.append(stats(chosen.where(invest, 0.0),
                      "A. FLEXIBLE — forecast (our strategy)", n_trials))
    rows.append(stats(R.mean(axis=1), "A. FLEXIBLE — passive (always in, equal weight)", n_trials))

    # ---------------- Regime B: must be invested every week --------------- #
    rows.append(stats(R.max(axis=1),
                      "B. FORCED — oracle (best pool each week, always in)", n_trials))
    rows.append(stats(chosen, "B. FORCED — forecast (best predicted pool, always in)", n_trials))
    rows.append(stats(R.mean(axis=1), "B. FORCED — passive (equal weight)", n_trials))
    for c in R.columns:
        rows.append(stats(R[c], f"B. FORCED — always {c}", n_trials))

    t = pd.DataFrame(rows)
    show = t.copy()
    for c in ("ann_return", "volatility", "max_drawdown", "total_return", "weeks_positive"):
        show[c] = show[c].map(lambda v: f"{v:+.1%}")
    for c in ("sharpe", "deflated_prob"):
        show[c] = show[c].map(lambda v: f"{v:6.2f}" if pd.notna(v) else "n/a")
    print(show[["strategy", "ann_return", "volatility", "sharpe", "max_drawdown",
                "weeks_positive", "deflated_prob", "beats_null"]].to_string(index=False))

    a_ceil = t.iloc[0].ann_return; a_act = t.iloc[1].ann_return; a_flr = t.iloc[2].ann_return
    b_ceil = t.iloc[3].ann_return; b_act = t.iloc[4].ann_return; b_flr = t.iloc[5].ann_return
    print("\n" + "=" * 84)
    print("WHAT THE RIGHT TO SIT OUT IS WORTH")
    print("=" * 84)
    print(f"  ceiling if you may hold cash      {a_ceil:+7.2%}   (Sharpe {t.iloc[0].sharpe:.2f})")
    print(f"  ceiling if you must be invested   {b_ceil:+7.2%}   (Sharpe {t.iloc[3].sharpe:.2f})")
    print(f"  value of the option to sit out    {a_ceil - b_ceil:+7.2%}")
    print(f"\n  edge available, flexible mandate  {a_ceil - a_flr:+7.2%}   "
          f"captured {(a_act - a_flr) / (a_ceil - a_flr):.0%}")
    print(f"  edge available, forced mandate    {b_ceil - b_flr:+7.2%}   "
          f"captured {(b_act - b_flr) / (b_ceil - b_flr):.0%}"
          if b_ceil != b_flr else "")

    t.to_csv(REPO_ROOT / "outputs" / "tables" / "allocation_regimes.csv", index=False)
    print(f"\nwrote outputs/tables/allocation_regimes.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
