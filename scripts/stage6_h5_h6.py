"""Stage 6 — H5 (is net return forecastable?) and H6 (theory vs ML on LVR).

Both under purged, embargoed cross-validation on identical folds. The panel is
weekly, targets are the following week, so purge = 7 days and embargo = 7 days.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.model.forecast import (diebold_mariano, fit_analytical_lvr,
                                fit_analytical_persistence, fit_lightgbm,
                                fit_mean_baseline, horse_race)
from src.model.purged_cv import PurgedKFold, verify_no_overlap
from src.model.volatility import har_rv_forecast
from src.utils.config import REPO_ROOT
from src.utils.speclog import log_specification

PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel.parquet"
DAILY = REPO_ROOT / "data" / "processed" / "h3_daily.parquet"
HEADLINE_POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")

FEATURES = [
    "realized_vol_7d", "realized_vol_30d", "vol_of_vol_30d", "implied_vol",
    "iv_rv_spread", "fee_tier_bps", "swaps_7d", "value_usd",
    "lvr_lag1", "lvr_analytical_lag1", "fees_lag1", "net_lag1",
]


def variance_series(pool: str) -> pd.DataFrame:
    """Current-week variance and the HAR-RV forecast for the following week.

    `rv_now` must be the variance of the week the analytical LVR was measured
    in. The panel's `realized_vol_7d` is deliberately lagged one week for use as
    a feature, so using it here would mismatch by a week — and since weekly
    variance ranges over a factor of thirty, dividing by the wrong week inflates
    the scaling by up to 33x. Both series are rebuilt here from the daily data,
    unlagged, and both are known at the forecast origin.
    """
    d = pd.read_parquet(DAILY)
    d = d[d.pool == pool].copy()
    d.index = pd.to_datetime(d["day"], utc=True)
    rv = (d["sigma_annual"].astype(float) ** 2).sort_index()
    now = rv.resample("W").mean()
    fcast = har_rv_forecast(rv, horizon_days=7, min_train=60).resample("W").last()
    out = pd.DataFrame({"rv_now": now, "rv_forecast": fcast})
    out["pool"] = pool
    return out.reset_index().rename(columns={out.index.name or "index": "week", "day": "week"})


def run(target: str, label: str, panel: pd.DataFrame, cv) -> list:
    d = panel.dropna(subset=[target] + FEATURES).reset_index(drop=True)
    d = d.sort_values("week").reset_index(drop=True)
    X = d[FEATURES].astype(float)
    X.index = pd.DatetimeIndex(d["week"])
    y = pd.Series(d[target].astype(float).to_numpy(), index=X.index)

    rep = verify_no_overlap(cv.split(X), pd.Series(X.index), 7, 7)
    print(f"\n  purged CV: {rep['n_folds']} folds, min train {rep['min_train_size']}, "
          f"leaks {len(rep['violations'])}  -> {'PASS' if rep['passed'] else 'FAIL'}")
    if not rep["passed"]:
        raise AssertionError("purged CV leaked; refusing to report a model result")

    print(f"  {len(y):,} pool-weeks, {d.pool.nunique()} pools\n")
    out = [fit_mean_baseline(X, y, cv), fit_lightgbm(X, y, cv)]
    return out, d, X, y


def main() -> int:
    panel = pd.read_parquet(PANEL)
    panel = panel[panel.pool.isin(HEADLINE_POOLS)].copy()
    cv = PurgedKFold(n_splits=5, purge_days=7, embargo_days=7)

    # ------------------------------------------------------------------ H5 --
    print("=" * 78)
    print("H5 — is next week's net LP return forecastable?")
    print("=" * 78)
    res5, d5, X5, y5 = run("target_net_next", "net return", panel, cv)
    t5 = horse_race(res5)
    print(t5.to_string(index=False, float_format=lambda v: f"{v:10.5f}"))
    ml, base = res5[1], res5[0]
    dm = diebold_mariano(base, ml, horizon=1)
    print(f"\n  Diebold-Mariano vs the mean baseline: stat {dm['dm_stat']:+.2f}, "
          f"p {dm['p_value']:.4f}, favours {dm.get('favours')}")
    verdict5 = ml.oos_r2 > 0 and dm["p_value"] < 0.05 and dm.get("favours") == ml.name
    print(f"\n  H5 VERDICT: {'net return is forecastable' if verdict5 else 'NOT forecastable — LightGBM does not beat the mean out of sample'}")
    if ml.feature_importance is not None:
        print("\n  feature importance (mean gain over folds):")
        print(ml.feature_importance.head(8).to_string())

    # ------------------------------------------------------------------ H6 --
    print("\n" + "=" * 78)
    print("H6 — theory vs ML on the LVR component")
    print("=" * 78)
    res6, d6, X6, y6 = run("target_lvr_next", "LVR", panel, cv)

    fcast = pd.concat([variance_series(p) for p in HEADLINE_POOLS], ignore_index=True)
    m = d6.merge(fcast, on=["pool", "week"], how="left")
    rv_now = m["rv_now"].astype(float)
    rv_f = m["rv_forecast"].astype(float)
    ana_now = m["lvr_analytical_usd"].astype(float)
    for s in (rv_now, rv_f, ana_now):
        s.index = X6.index
    ratio = (rv_f / rv_now).replace([np.inf, -np.inf], np.nan)
    print(f"  variance-scaling ratio: median {ratio.median():.3f}, "
          f"p1 {ratio.quantile(.01):.3f}, p99 {ratio.quantile(.99):.3f}")

    res6.append(fit_analytical_lvr(ana_now, rv_now, rv_f, y6, cv))
    res6.append(fit_analytical_persistence(ana_now, y6, cv))

    t6 = horse_race(res6)
    print(t6.to_string(index=False, float_format=lambda v: f"{v:10.4f}"))

    by_name = {r.name: r for r in res6}
    theory = by_name.get("σ²/8 + HAR-RV")
    mlr = by_name.get("LightGBM")
    dm6 = diebold_mariano(theory, mlr, horizon=1)
    print(f"\n  Diebold-Mariano, theory vs LightGBM: stat {dm6['dm_stat']:+.2f}, "
          f"p {dm6['p_value']:.4f}, favours {dm6.get('favours')}")
    winner = t6.iloc[0]["model"]
    print(f"\n  H6 VERDICT: {winner} wins on out-of-sample RMSE"
          f"{'  — THEORY BEATS ML' if 'σ' in winner else ''}")
    if dm6["p_value"] > 0.05:
        print("  (the difference is not statistically significant — a tie is still")
        print("   a strong result for a one-parameter derivation against a fitted model)")

    out = REPO_ROOT / "outputs" / "tables"
    t5.to_csv(out / "h5_forecast.csv", index=False)
    t6.to_csv(out / "h6_horse_race.csv", index=False)
    if ml.feature_importance is not None:
        ml.feature_importance.to_csv(out / "h5_feature_importance.csv")
    for stage, comp, r in (("6", "h5_net_return", ml), ("6", "h6_lvr_theory", theory)):
        log_specification(stage=stage, component=comp,
                          params={"features": FEATURES, "cv": "purged_5fold_7d_7d"},
                          metric_name="oos_rmse", metric_value=r.oos_rmse)
    print(f"\nwrote outputs/tables/h5_forecast.csv and h6_horse_race.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
