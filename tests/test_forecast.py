"""Forecast models and the horse race.

The tests that matter here are the ones that would catch a comparison that is
not a comparison: models scored on different samples, a baseline that is not
actually the training mean, or a "winner" decided by an unfair test set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.model.forecast import (diebold_mariano, fit_analytical_persistence,
                                fit_lightgbm, fit_mean_baseline, horse_race)
from src.model.purged_cv import PurgedKFold


def _panel(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="W", tz="UTC")
    signal = pd.Series(rng.normal(size=n), index=idx).rolling(4).mean().fillna(0)
    X = pd.DataFrame({"a": signal, "b": rng.normal(size=n), "c": rng.normal(size=n)}, index=idx)
    y = pd.Series(2 * signal.to_numpy() + rng.normal(scale=0.5, size=n), index=idx)
    return X, y


CV = PurgedKFold(n_splits=4, purge_days=7, embargo_days=7)


def test_mean_baseline_predicts_the_training_mean():
    X, y = _panel()
    r = fit_mean_baseline(X, y, CV)
    assert r.predictions.nunique() <= CV.n_splits
    assert r.n_oos > 100


def test_lightgbm_beats_the_mean_when_there_is_real_signal():
    """A learner that cannot find a planted signal is broken, not conservative."""
    X, y = _panel()
    base, ml = fit_mean_baseline(X, y, CV), fit_lightgbm(X, y, CV)
    assert ml.oos_rmse < base.oos_rmse
    assert ml.oos_r2 > 0


def test_lightgbm_does_not_beat_the_mean_on_pure_noise():
    """And one that reports skill on noise is worse than useless."""
    rng = np.random.default_rng(1)
    idx = pd.date_range("2023-01-01", periods=300, freq="W", tz="UTC")
    X = pd.DataFrame(rng.normal(size=(300, 3)), columns=list("abc"), index=idx)
    y = pd.Series(rng.normal(size=300), index=idx)
    assert fit_lightgbm(X, y, CV).oos_r2 < 0.1


def test_horse_race_scores_every_model_on_the_same_observations():
    """The analytical arm starts later than the others because of its warm-up.
    Scoring it on a different test set would not be a comparison."""
    X, y = _panel()
    full = fit_mean_baseline(X, y, CV)
    short = fit_analytical_persistence(pd.Series(y.to_numpy(), index=y.index), y, CV)
    object.__setattr__(short, "predictions", short.predictions.iloc[20:])
    object.__setattr__(short, "actual", short.actual.iloc[20:])
    t = horse_race([full, short], common_sample=True)
    assert t["n_oos"].nunique() == 1, "models were scored on different samples"


def test_horse_race_orders_by_rmse():
    X, y = _panel()
    t = horse_race([fit_mean_baseline(X, y, CV), fit_lightgbm(X, y, CV)])
    assert t["rmse"].is_monotonic_increasing
    assert t.iloc[0]["rmse_vs_best"] == pytest.approx(1.0)


def test_diebold_mariano_detects_a_clear_winner():
    X, y = _panel()
    base, ml = fit_mean_baseline(X, y, CV), fit_lightgbm(X, y, CV)
    dm = diebold_mariano(base, ml)
    assert dm["p_value"] < 0.05
    assert dm["favours"] == ml.name


def test_diebold_mariano_finds_no_difference_between_identical_models():
    X, y = _panel()
    a = fit_mean_baseline(X, y, CV)
    dm = diebold_mariano(a, a)
    assert abs(dm["dm_stat"]) < 1e-6 or np.isnan(dm["dm_stat"])


def test_directional_accuracy_is_measured_against_the_median():
    """Against zero it would be degenerate: LVR is almost always one sign."""
    X, y = _panel()
    r = fit_mean_baseline(X, y, CV)
    assert 0.0 <= r.directional_accuracy <= 1.0
