"""Volatility estimators for the analytical LVR arm.

Open question 2: which estimator best matches empirical LVR is itself an
empirical question. Microstructure noise argues against 1-minute sampling;
jumps argue for bipower variation, since the sigma^2/8 result is derived under
a diffusion and jump moves are not arbitraged the same way a diffusive drift is.

Baseline: realized variance from 5-minute log returns, trailing 24h,
annualised by sqrt(365 * 24 * 12).
"""

from __future__ import annotations

import pandas as pd


def realized_variance(prices: pd.Series, sample_minutes: int = 5, window_hours: int = 24) -> pd.Series:
    """Trailing realized variance from log returns at the given sampling frequency."""
    raise NotImplementedError("Stage 3.2")


def garman_klass(ohlc: pd.DataFrame, window_hours: int = 24) -> pd.Series:
    """Range-based estimator. More efficient per observation; sensitive to gaps."""
    raise NotImplementedError("Stage 3.2")


def bipower_variation(prices: pd.Series, sample_minutes: int = 5, window_hours: int = 24) -> pd.Series:
    """Jump-robust estimator.

    Isolates the continuous component of quadratic variation. If sigma^2/8
    tracks empirical LVR better under bipower than under plain RV, that says
    jumps are not being arbitraged the way the theory's diffusion assumes —
    which is a finding, not a nuisance.
    """
    raise NotImplementedError("Stage 3.2")


def har_rv_forecast(rv: pd.Series, horizon_days: int = 7) -> pd.Series:
    """HAR-RV: daily, weekly and monthly realized variance components.

    The volatility forecast feeding the analytical arm of the H6 horse race.
    Fitted strictly on data available at t — no lookahead, tested.
    """
    raise NotImplementedError("Stage 6.3 — H6 baseline")


def garch_forecast(returns: pd.Series, horizon_days: int = 7) -> pd.Series:
    """GARCH(1,1) alternative to HAR-RV, as a robustness arm."""
    raise NotImplementedError("Stage 6.3")


def estimator_horse_race(prices: pd.Series, empirical_lvr: pd.Series) -> pd.DataFrame:
    """Open question 2: rank estimators by how well sigma^2/8 tracks empirical LVR."""
    raise NotImplementedError("Stage 3.2 — open question 2")
