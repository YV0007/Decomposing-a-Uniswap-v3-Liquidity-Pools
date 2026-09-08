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

from src.model.forecast import fit_calibrated_lvr, fit_lightgbm
from src.model.purged_cv import PurgedKFold
from src.model.volatility import har_family_forecast, har_rv_forecast
from src.utils.config import REPO_ROOT
from src.utils.speclog import count_specifications
from src.utils.stats import deflated_sharpe_ratio

PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel_all.parquet"
DAILY = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
#: ETH/USDC 100bp is excluded: a $100k position is 113% of its active liquidity,
#: so it is not a price-taker and its returns are not measurements (DECISIONS 5.7).
POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp", "WBTC_ETH_30bp", "WBTC_USDC_30bp",
         "USDC_USDT_1bp")
NOTIONAL, GAS_WEEK, WK = 100_000.0, 22.39 / 100_000, 52
FEE_FEATURES = ["fees_lag1", "fees_usd", "realized_vol_7d", "swaps_7d"]


VARIANT = "harq"   # HAR-Q won the volatility race on both QLIKE and RMSE


def variance_series(pool: str) -> pd.DataFrame:
    """Current and forecast variance for a pool, from its own reference series.

    Uses HAR-Q where realised measures exist for the pool's CEX symbol. HAR-Q
    discounts the daily term by `sqrt(RQ)`, since a day's realised variance is
    itself estimated with error — it beat HAR-RV on both QLIKE (0.970x) and RMSE
    (0.975x) with R² rising from 0.114 to 0.157. Falls back to HAR-RV on the
    derived table when the measures are missing.

    Both columns come from the same source so the ratio that scales analytical
    LVR is on a consistent footing.
    """
    from src.utils.config import pool as get_pool

    spec = get_pool(pool)
    mpath = REPO_ROOT / "data" / "processed" / f"realised_measures_{spec.cex_symbol}.parquet"
    if mpath.exists():
        ms = pd.read_parquet(mpath).sort_index()
        ms.index = pd.to_datetime(ms.index, utc=True)
        fc = har_family_forecast(ms, VARIANT, 7, 60)
        out = pd.DataFrame({"rv_now": ms["rv"].resample("W").mean(),
                            "rv_forecast": fc.resample("W").last()})
    else:
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
    # Raw analytical LVR is a biased forecast (H3: slope 0.81, positive
    # intercept), and the bias is largest in dollars on the pools with the most
    # LVR. Calibrate it on training folds only.
    d["target_lvr_next"] = d.groupby("pool")["lvr_usd"].shift(-1)
    scaled = (d["lvr_analytical_usd"].astype(float)
              * (d["rv_forecast"].astype(float) / d["rv_now"].astype(float)))
    scaled.index = X.index
    lvr_y = pd.Series(d["target_lvr_next"].astype(float).to_numpy(), index=X.index)
    pools_s = pd.Series(d["pool"].to_numpy(), index=X.index)
    ok = lvr_y.notna() & scaled.notna() & np.isfinite(scaled)
    cal_res, cal = fit_calibrated_lvr(scaled.where(ok), lvr_y.where(ok), cv, pools_s)
    print(f"  LVR forecast: raw analytical vs calibrated — calibrated OOS R² "
          f"{cal_res.oos_r2:+.3f}\n")
    d["pred_lvr"] = cal.reindex(X.index).to_numpy() / NOTIONAL
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
