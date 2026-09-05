"""Forecast models and the H6 horse race.

H5 asks whether net return is forecastable at all. H6 races the closed form
against the black box on the LVR component specifically.

**If the closed form wins, that is the better result** and it leads. Theory
outperforming gradient boosting is rarer than the reverse and signals
understanding rather than fashion.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ForecastResult:
    predictions: pd.Series
    oos_rmse: float
    oos_r2: float
    directional_accuracy: float
    feature_importance: pd.Series | None
    n_specifications_tried: int


def fit_lightgbm(X: pd.DataFrame, y: pd.Series, cv, config: dict) -> ForecastResult:
    """Gradient boosting on the feature set, under purged CV.

    Every configuration tried is appended to the specification log at the point
    of running, so the Deflated Sharpe later has an honest trial count.
    """
    raise NotImplementedError("Stage 6.2 — H5")


def fit_mean_baseline(y: pd.Series, cv) -> ForecastResult:
    """Predict the historical mean.

    The bar LightGBM has to clear. If it does not clear it out of sample, the
    paper says so.
    """
    raise NotImplementedError("Stage 6.2")


def fit_analytical_lvr_forecast(vol_forecast: pd.Series, pool_value: pd.Series) -> ForecastResult:
    """The theory arm: sigma^2/8 fed a HAR-RV volatility forecast.

    One free parameter set by derivation rather than fitting, which is exactly
    why it is worth racing against a model with hundreds.
    """
    raise NotImplementedError("Stage 6.3 — H6")


def horse_race_h6(analytical: ForecastResult, ml: ForecastResult) -> pd.DataFrame:
    """Head-to-head on identical out-of-sample folds.

    Reports RMSE and directional accuracy for both. Same folds, same target,
    same embargo — otherwise the comparison is not a comparison.
    """
    raise NotImplementedError("Stage 6.3 — H6")
