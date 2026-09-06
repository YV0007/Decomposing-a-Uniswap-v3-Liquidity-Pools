"""Forecast models and the H6 horse race.

H5 asks whether net LP return is forecastable at all. H6 races the closed form
against the black box on the LVR component specifically.

**If the closed form wins, that is the better result** and it leads. Theory
outperforming gradient boosting is rarer than the reverse and signals
understanding rather than fashion. It is also the fair fight here: the
analytical arm has *one* parameter, set by derivation, and cannot overfit; the
ML arm has hundreds fitted on ~180 pool-weeks.

Every model is evaluated on identical purged, embargoed folds. Anything else is
not a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastResult:
    name: str
    predictions: pd.Series          # out-of-sample, indexed like the input
    actual: pd.Series
    oos_rmse: float
    oos_mae: float
    oos_r2: float                   # vs predicting the training mean
    directional_accuracy: float
    n_oos: int
    feature_importance: pd.Series | None = None
    n_specifications_tried: int = 1
    notes: list[str] = field(default_factory=list)


def _score(name: str, pred: pd.Series, actual: pd.Series, baseline: float,
           importance=None, n_specs: int = 1) -> ForecastResult:
    m = pred.notna() & actual.notna()
    p, a = pred[m], actual[m]
    err = p - a
    ss_res = float((err**2).sum())
    ss_tot = float(((a - baseline) ** 2).sum())
    # Directional accuracy against the sample median, so "up or down" means
    # "busier or quieter than typical" rather than "positive or negative",
    # which is degenerate for a series that is almost always one sign.
    med = float(a.median())
    da = float(((p > med) == (a > med)).mean()) if len(a) else float("nan")
    return ForecastResult(
        name=name, predictions=p, actual=a,
        oos_rmse=float(np.sqrt((err**2).mean())), oos_mae=float(err.abs().mean()),
        oos_r2=1 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        directional_accuracy=da, n_oos=len(a),
        feature_importance=importance, n_specifications_tried=n_specs,
    )


def _oos_frame(X: pd.DataFrame, y: pd.Series, cv):
    """Collect out-of-sample predictions across the purged folds."""
    return [(tr, te) for tr, te in cv.split(X)]


def fit_mean_baseline(X: pd.DataFrame, y: pd.Series, cv) -> ForecastResult:
    """Predict the training mean. The bar every other model must clear.

    A model that cannot beat this out of sample has found nothing, and the paper
    says so rather than reporting its R-squared against zero.
    """
    pred = pd.Series(index=y.index, dtype=float)
    for tr, te in _oos_frame(X, y, cv):
        pred.iloc[te] = y.iloc[tr].mean()
    return _score("mean baseline", pred, y, float(y.mean()))


def fit_lightgbm(X: pd.DataFrame, y: pd.Series, cv, params: dict | None = None,
                 name: str = "LightGBM") -> ForecastResult:
    """Gradient boosting under purged cross-validation.

    Deliberately small: ~180 usable pool-weeks per pool cannot support a deep
    model, and the honest response to a small sample is a constrained learner
    rather than a large one plus hope.
    """
    import lightgbm as lgb

    p = {
        "n_estimators": 300, "learning_rate": 0.03, "num_leaves": 7,
        "min_child_samples": 20, "subsample": 0.8, "subsample_freq": 1,
        "colsample_bytree": 0.8, "reg_lambda": 1.0, "verbose": -1,
        "random_state": 42,
    }
    p.update(params or {})

    pred = pd.Series(index=y.index, dtype=float)
    importances = np.zeros(X.shape[1])
    folds = 0
    for tr, te in _oos_frame(X, y, cv):
        model = lgb.LGBMRegressor(**p)
        model.fit(X.iloc[tr], y.iloc[tr])
        pred.iloc[te] = model.predict(X.iloc[te])
        importances += model.feature_importances_
        folds += 1
    imp = pd.Series(importances / max(1, folds), index=X.columns).sort_values(ascending=False)
    return _score(name, pred, y, float(y.mean()), importance=imp)


def fit_analytical_lvr(
    lvr_analytical_now: pd.Series, rv_now: pd.Series, rv_forecast: pd.Series,
    y: pd.Series, cv, name: str = "σ²/8 + HAR-RV",
) -> ForecastResult:
    """The theory arm: scale this week's analytical LVR by the variance forecast.

    LVR is linear in variance at a fixed range and position value, so

        predicted_next = analytical_now * (rv_forecast / rv_now)

    Everything on the right is known at the forecast origin: `analytical_now` is
    this week's realised analytical LVR, and `rv_forecast` comes from a HAR fit
    on data strictly before it.

    No parameters are fitted here at all — the constant comes from the
    derivation. It is scored on the same folds as the others so the comparison
    means something, even though it does not use the training half.
    """
    ratio = (rv_forecast / rv_now).replace([np.inf, -np.inf], np.nan)
    raw = lvr_analytical_now * ratio
    pred = pd.Series(index=y.index, dtype=float)
    for _, te in _oos_frame(pd.DataFrame(index=y.index), y, cv):
        pred.iloc[te] = raw.iloc[te]
    return _score(name, pred, y, float(y.mean()))


def fit_analytical_persistence(
    lvr_analytical_now: pd.Series, y: pd.Series, cv,
) -> ForecastResult:
    """The theory arm with the simplest possible volatility forecast: persistence.

    Included because if HAR-RV cannot beat "assume variance stays where it is",
    the volatility model is not earning its place and the horse race is really
    about the closed form alone.
    """
    pred = pd.Series(index=y.index, dtype=float)
    for _, te in _oos_frame(pd.DataFrame(index=y.index), y, cv):
        pred.iloc[te] = lvr_analytical_now.iloc[te]
    return _score("σ²/8 + persistence", pred, y, float(y.mean()))


def horse_race(results: list[ForecastResult], common_sample: bool = True) -> pd.DataFrame:
    """Head-to-head on identical folds. Lower RMSE wins.

    `common_sample` restricts every model to the observations *all* of them
    could predict. The analytical arm needs a HAR warm-up and so starts later
    than the others; comparing its RMSE on 352 rows against a baseline's on 366
    would not be a comparison. The intersection is small here (14 rows) but the
    principle is not negotiable — the headline claim is that one model beats
    another, and that requires the same test set.
    """
    if common_sample:
        idx = results[0].predictions.index
        for r in results[1:]:
            idx = idx.intersection(r.predictions.index)
        scored = []
        for r in results:
            p, a = r.predictions.loc[idx], r.actual.loc[idx]
            scored.append(_score(r.name, p, a, float(a.mean()),
                                 importance=r.feature_importance,
                                 n_specs=r.n_specifications_tried))
        results = scored

    rows = [{
        "model": r.name, "n_oos": r.n_oos, "rmse": r.oos_rmse, "mae": r.oos_mae,
        "oos_r2": r.oos_r2, "directional_accuracy": r.directional_accuracy,
    } for r in results]
    t = pd.DataFrame(rows).sort_values("rmse").reset_index(drop=True)
    t["rmse_vs_best"] = t["rmse"] / t.iloc[0]["rmse"]
    return t


def diebold_mariano(a: ForecastResult, b: ForecastResult, horizon: int = 1) -> dict:
    """Diebold-Mariano test on squared-error loss.

    Whether one model's edge is larger than sampling noise. Newey-West variance
    with `horizon - 1` lags, because overlapping forecasts make the loss
    differential autocorrelated and the naive test would over-reject.
    """
    from scipy import stats as sps

    idx = a.predictions.index.intersection(b.predictions.index)
    if len(idx) < 20:
        return {"n": len(idx), "dm_stat": float("nan"), "p_value": float("nan")}
    la = (a.predictions.loc[idx] - a.actual.loc[idx]) ** 2
    lb = (b.predictions.loc[idx] - b.actual.loc[idx]) ** 2
    d = (la - lb).to_numpy(float)
    n = len(d)
    lags = max(0, horizon - 1)
    gamma0 = float(((d - d.mean()) ** 2).mean())
    var = gamma0
    for k in range(1, lags + 1):
        cov = float(((d[k:] - d.mean()) * (d[:-k] - d.mean())).mean())
        var += 2 * (1 - k / (lags + 1)) * cov
    stat = d.mean() / np.sqrt(max(var, 1e-18) / n)
    return {
        "n": n, "dm_stat": float(stat),
        "p_value": float(2 * (1 - sps.norm.cdf(abs(stat)))),
        "favours": b.name if stat > 0 else a.name,
    }
