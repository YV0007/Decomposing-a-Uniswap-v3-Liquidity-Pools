"""Purged CV and the statistical machinery.

The load-bearing tests here are the ones showing the purge actually closes a
leak — an implementation that silently purges nothing would pass a
"does it run" test and inflate every out-of-sample number in the paper.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.model.purged_cv import PurgedKFold, verify_no_overlap
from src.utils.stats import (block_bootstrap_ci, deflated_sharpe_ratio,
                             expected_max_sharpe, newey_west_lags, newey_west_ols)

HORIZON = 7


def _daily(n=400):
    ts = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"x": np.arange(n, dtype=float)}, index=ts)


# --------------------------------------------------------------------------- #
# Purged CV
# --------------------------------------------------------------------------- #

def test_folds_cover_every_observation_exactly_once():
    X = _daily()
    cv = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=HORIZON)
    test_all = np.concatenate([te for _, te in cv.split(X)])
    assert sorted(test_all.tolist()) == list(range(len(X)))


def test_no_target_window_reaches_into_its_test_fold():
    X = _daily()
    cv = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=HORIZON)
    ts = pd.Series(X.index)
    rep = verify_no_overlap(cv.split(X), ts, HORIZON, HORIZON)
    assert rep["passed"], rep["violations"]
    assert rep["n_folds"] == 5


def test_purging_actually_removes_something():
    """A purge that removes nothing would pass a 'does it run' test.

    Compare against the naive split — everything outside the test fold — and
    require the purged training set to be strictly smaller.
    """
    X = _daily()
    cv = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=HORIZON)
    for train_idx, test_idx in cv.split(X):
        naive = len(X) - len(test_idx)
        assert len(train_idx) < naive, "purge removed no observations"


def test_a_naive_split_would_leak_where_the_purge_does_not():
    """Demonstrates the leak the purge exists to close."""
    X = _daily()
    ts = pd.Series(X.index)
    cv = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=0)

    naive_splits = []
    for _, test_idx in cv.split(X):
        train = np.setdiff1d(np.arange(len(X)), test_idx)
        naive_splits.append((train, test_idx))
    naive_report = verify_no_overlap(naive_splits, ts, HORIZON, 0)
    assert not naive_report["passed"], "the naive split should leak"

    purged_report = verify_no_overlap(cv.split(X), ts, HORIZON, 0)
    assert purged_report["passed"]


def test_embargo_removes_observations_after_the_test_fold():
    X = _daily()
    ts = pd.Series(X.index)
    no_emb = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=0)
    with_emb = PurgedKFold(n_splits=5, purge_days=HORIZON, embargo_days=21)
    a = [len(tr) for tr, _ in no_emb.split(X)]
    b = [len(tr) for tr, _ in with_emb.split(X)]
    assert sum(b) < sum(a)


def test_unsorted_input_is_rejected():
    X = _daily().sample(frac=1, random_state=0)
    with pytest.raises(ValueError, match="sorted by time"):
        list(PurgedKFold().split(X))


def test_timestamp_column_is_accepted():
    X = _daily().reset_index(names="timestamp")
    assert len(list(PurgedKFold(n_splits=3).split(X))) == 3


# --------------------------------------------------------------------------- #
# Newey-West OLS
# --------------------------------------------------------------------------- #

def test_recovers_a_known_relationship():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=800))
    y = 0.4 + 1.7 * x + pd.Series(rng.normal(scale=0.2, size=800))
    r = newey_west_ols(y, x)
    assert r.beta == pytest.approx(1.7, abs=0.03)
    assert r.alpha == pytest.approx(0.4, abs=0.03)
    assert r.r_squared > 0.95


def _ar1(rng, n, rho=0.9, scale=1.0):
    v = np.zeros(n)
    for i in range(1, n):
        v[i] = rho * v[i - 1] + rng.normal(scale=scale)
    return v


def test_hac_inflates_the_intercept_when_only_the_errors_are_persistent():
    """With i.i.d. x, the product x_t * e_t is serially uncorrelated even when
    e is AR(1), so HAC correctly leaves beta alone and inflates only alpha —
    whose regressor is the constant, making 1 * e_t inherit e's persistence."""
    rng = np.random.default_rng(1)
    n = 600
    x = pd.Series(rng.normal(size=n))
    y = pd.Series(x.to_numpy() + _ar1(rng, n))
    hac, plain = newey_west_ols(y, x, lags=20), newey_west_ols(y, x, lags=0)
    assert hac.alpha_se > 2 * plain.alpha_se
    assert hac.beta_se == pytest.approx(plain.beta_se, rel=0.15)


def test_hac_inflates_beta_when_both_series_are_persistent():
    """The H3 setting. Empirical and analytical LVR are both highly persistent,
    so x_t * e_t is autocorrelated and plain OLS standard errors are too small —
    the difference between 'the theory holds' and 'we cannot tell'."""
    rng = np.random.default_rng(1)
    n = 600
    x = pd.Series(_ar1(rng, n))
    y = pd.Series(x.to_numpy() + _ar1(rng, n))
    hac, plain = newey_west_ols(y, x, lags=20), newey_west_ols(y, x, lags=0)
    assert hac.beta_se > plain.beta_se


def test_beta_equals_one_test_matches_h3_framing():
    rng = np.random.default_rng(2)
    x = pd.Series(rng.normal(size=500).cumsum() + 100)
    y = pd.Series(x.to_numpy() + rng.normal(scale=0.5, size=500))
    r = newey_west_ols(y, x)
    assert r.beta_equals(1.0) > 0.05, "beta should not be distinguishable from 1"
    lo, hi = r.beta_ci()
    assert lo < 1.0 < hi


def test_lag_rule_of_thumb():
    assert newey_west_lags(100) == 4
    assert newey_west_lags(1000) >= 4


def test_too_few_observations_raise():
    with pytest.raises(ValueError, match="at least 3"):
        newey_west_ols(pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]))


# --------------------------------------------------------------------------- #
# Deflated Sharpe
# --------------------------------------------------------------------------- #

def test_expected_max_sharpe_grows_with_the_number_of_trials():
    """The bar rises with the size of the search. This is the whole mechanism."""
    v = 1 / 100
    assert expected_max_sharpe(2, v) < expected_max_sharpe(50, v) < expected_max_sharpe(5000, v)


def test_deflation_penalises_a_large_search():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(loc=0.004, scale=0.02, size=300))
    few = deflated_sharpe_ratio(r, n_trials=1)
    many = deflated_sharpe_ratio(r, n_trials=10_000)
    assert few["sharpe"] == pytest.approx(many["sharpe"])
    assert many["deflated_sharpe_prob"] < few["deflated_sharpe_prob"]


def test_pure_noise_searched_hard_does_not_clear_the_bar():
    """The result the deflation exists to prevent: the best of many noise
    strategies looking like skill."""
    rng = np.random.default_rng(4)
    r = pd.Series(rng.normal(loc=0.0, scale=0.02, size=200))
    assert not deflated_sharpe_ratio(r, n_trials=5_000)["beats_null"]


def test_deflation_reports_the_shape_of_the_return_distribution():
    """Skew and kurtosis enter the deflation directly: negative skew and fat
    tails mean a given raw Sharpe is worth less."""
    from scipy import stats as sps

    left_skewed = pd.Series(-sps.skewnorm.rvs(a=8, size=500, random_state=11) * 0.02 + 0.006)
    symmetric = pd.Series(np.random.default_rng(5).normal(loc=0.006, scale=0.02, size=500))
    a = deflated_sharpe_ratio(symmetric, n_trials=10)
    b = deflated_sharpe_ratio(left_skewed, n_trials=10)
    assert b["skew"] < 0 < abs(a["skew"]) + 1
    assert b["skew"] < a["skew"]


def test_zero_variance_returns_are_rejected():
    with pytest.raises(ValueError, match="zero variance"):
        deflated_sharpe_ratio(pd.Series([0.01] * 50), n_trials=1)


# --------------------------------------------------------------------------- #
# Block bootstrap
# --------------------------------------------------------------------------- #

def test_block_bootstrap_brackets_the_sample_mean():
    rng = np.random.default_rng(6)
    s = pd.Series(rng.normal(loc=0.5, scale=1.0, size=500))
    lo, hi = block_bootstrap_ci(s, block_size=20, n_boot=400)
    assert lo < s.mean() < hi


def test_block_bootstrap_is_reproducible():
    s = pd.Series(np.random.default_rng(7).normal(size=300))
    assert block_bootstrap_ci(s, seed=1, n_boot=200) == block_bootstrap_ci(s, seed=1, n_boot=200)


def test_block_bootstrap_rejects_a_series_shorter_than_the_block():
    with pytest.raises(ValueError, match="shorter"):
        block_bootstrap_ci(pd.Series([1.0, 2.0, 3.0]), block_size=20)
