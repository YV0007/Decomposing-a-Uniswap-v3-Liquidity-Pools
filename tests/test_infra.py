"""Infrastructure: volatility forecasts, cohorts, features, hedging.

These are the pieces built so the analysis stages have something to stand on.
The tests that matter are the ones that would catch a component silently doing
nothing — a forecast that has no skill, a gate that never fails, a hedge that
does not hedge.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.build.hedge import accrued_funding, rebalance_timestamps
from src.build.position import cohort_entry_blocks
from src.model.features import assert_no_lookahead, liquidity_concentration
from src.model.volatility import (ewma_forecast, har_components, har_rv_forecast,
                                  realized_variance, to_sampled_prices)


def _persistent_rv(n=500, seed=0):
    """AR(1) variance — persistent, so a forecast should find it."""
    rng = np.random.default_rng(seed)
    v = np.zeros(n)
    v[0] = 0.09
    for i in range(1, n):
        v[i] = max(1e-4, 0.05 + 0.9 * (v[i - 1] - 0.05) + rng.normal(scale=0.006))
    return pd.Series(v, index=pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC"))


# --------------------------------------------------------------------------- #
# Volatility forecasts
# --------------------------------------------------------------------------- #

def test_har_finds_signal_when_variance_is_persistent():
    rv = _persistent_rv()
    f = har_rv_forecast(rv, horizon_days=7)
    realised = rv.shift(-1).rolling(7).mean().shift(-6)
    both = pd.concat([f, realised], axis=1).dropna()
    assert len(both) > 100
    assert both.corr().iloc[0, 1] > 0.5, "HAR should track a persistent variance process"


def test_har_finds_nothing_in_white_noise():
    """A forecast that reports skill on noise is worse than useless."""
    rng = np.random.default_rng(1)
    rv = pd.Series(np.abs(rng.normal(0.3, 0.08, 400)) ** 2,
                   index=pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC"))
    f = har_rv_forecast(rv, horizon_days=7)
    realised = rv.shift(-1).rolling(7).mean().shift(-6)
    both = pd.concat([f, realised], axis=1).dropna()
    assert abs(both.corr().iloc[0, 1]) < 0.25


def test_har_is_fit_only_on_the_past():
    """Truncating the future must not change an earlier forecast."""
    rv = _persistent_rv()
    full = har_rv_forecast(rv, 7)
    cut = har_rv_forecast(rv.iloc[:300], 7)
    common = full.dropna().index.intersection(cut.dropna().index)
    assert len(common) > 50
    assert np.allclose(full.loc[common], cut.loc[common], rtol=1e-9)


def test_har_components_are_ordered_windows():
    rv = _persistent_rv(100)
    c = har_components(rv)
    assert list(c.columns) == ["rv_d", "rv_w", "rv_m"]
    assert c["rv_w"].isna().sum() < c["rv_m"].isna().sum()


def test_ewma_is_lagged():
    rv = _persistent_rv(120)
    e = ewma_forecast(rv)
    assert e.iloc[0] != e.iloc[0] or pd.isna(e.iloc[0])   # first is NaN after the shift


def test_realized_variance_is_shifted_off_its_own_window():
    px = pd.Series(np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.001, 20000))) * 1200,
                   index=pd.date_range("2023-01-01", periods=20000, freq="1min", tz="UTC"))
    rv = realized_variance(px, sample_minutes=5, window_hours=24)
    assert rv.dropna().gt(0).all()
    assert rv.isna().iloc[0]


# --------------------------------------------------------------------------- #
# Cohorts
# --------------------------------------------------------------------------- #

def test_cohorts_open_on_or_after_each_month_boundary():
    ts = pd.date_range("2023-01-01", "2023-04-15", freq="6h", tz="UTC")
    blocks = pd.DataFrame({
        "block_number": range(len(ts)),
        "block_timestamp": (ts.astype("int64") // 10**9).to_numpy(),
    })
    entries = cohort_entry_blocks(blocks, freq="MS")
    assert len(entries) == 4
    got = pd.to_datetime(
        blocks.set_index("block_number").loc[entries, "block_timestamp"], unit="s", utc=True
    )
    for t in got:
        assert t.day == 1, "a cohort must open on the first traded block of its month"


def test_cohorts_are_empty_for_empty_input():
    assert cohort_entry_blocks(pd.DataFrame(columns=["block_number", "block_timestamp"])) == []


# --------------------------------------------------------------------------- #
# Hedge mechanics
# --------------------------------------------------------------------------- #

def test_rebalance_schedule_spans_the_period():
    s = rebalance_timestamps(1000, 1000 + 86_400 * 3, 86_400)
    assert s[0] == 1000 and len(s) == 4


def test_a_short_pays_when_funding_is_positive():
    """Sign convention: positive funding means the short pays."""
    f = pd.DataFrame({"timestamp_ms": [1_000_000 * 1000], "funding_rate": ["0.0001"]})
    paid = accrued_funding(f, 999_000, 1_001_000, Decimal("100000"))
    assert paid < 0, "positive funding on a short is a cost"


def test_funding_outside_the_window_is_not_charged():
    f = pd.DataFrame({"timestamp_ms": [5_000_000 * 1000], "funding_rate": ["0.0001"]})
    assert accrued_funding(f, 999_000, 1_001_000, Decimal("100000")) == 0


# --------------------------------------------------------------------------- #
# Feature gate
# --------------------------------------------------------------------------- #

def test_lookahead_gate_passes_on_clean_features():
    rng = np.random.default_rng(3)
    n = 200
    idx = pd.date_range("2023-01-01", periods=n, freq="W", tz="UTC")
    y = pd.Series(rng.normal(size=n), index=idx)
    X = pd.DataFrame({"a": y.shift(2) + rng.normal(scale=2, size=n),
                      "b": rng.normal(size=n)}, index=idx)
    assert assert_no_lookahead(X, y)["passed"]


def test_lookahead_gate_catches_a_planted_leak():
    """The gate must fail on a feature that is the target itself.

    A gate that never fires is worse than no gate, because it reads as evidence.
    """
    rng = np.random.default_rng(4)
    n = 200
    idx = pd.date_range("2023-01-01", periods=n, freq="W", tz="UTC")
    y = pd.Series(rng.normal(size=n), index=idx)
    X = pd.DataFrame({"leak": y + rng.normal(scale=0.05, size=n)}, index=idx)
    with pytest.raises(AssertionError, match="no-lookahead gate FAILED"):
        assert_no_lookahead(X, y)


def test_lookahead_gate_needs_enough_observations():
    idx = pd.date_range("2023-01-01", periods=5, freq="W", tz="UTC")
    with pytest.raises(ValueError, match="at least 20"):
        assert_no_lookahead(pd.DataFrame({"a": range(5)}, index=idx),
                            pd.Series(range(5), index=idx))


def test_liquidity_concentration_is_bounded():
    spread = pd.Series([1.0] * 100)
    concentrated = pd.Series([100.0] + [0.0] * 99)
    assert liquidity_concentration(spread) == pytest.approx(0.01)
    assert liquidity_concentration(concentrated) == pytest.approx(1.0)
    assert np.isnan(liquidity_concentration(pd.Series([0.0, 0.0])))
