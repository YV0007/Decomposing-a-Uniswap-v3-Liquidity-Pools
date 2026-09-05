"""Volatility estimators for the analytical LVR arm.

Open question 2: which estimator best matches empirical LVR is itself an
empirical question. Microstructure noise argues against 1-minute sampling;
jumps argue for bipower variation, since the sigma^2/8 result is derived under a
diffusion and a jump is not arbitraged the way a diffusive drift is.

Baseline: realized variance from 5-minute log returns over a trailing 24h,
annualised on the single convention in `config.yaml`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Annualisation base. Crypto trades continuously; there is no 252 here.
DAYS_PER_YEAR = 365
SECONDS_PER_YEAR = DAYS_PER_YEAR * 24 * 3600


def to_sampled_prices(cex: pd.DataFrame, sample_minutes: int = 5) -> pd.Series:
    """Downsample a 1s kline series to the estimator's sampling frequency.

    Takes the last close in each bucket, indexed by the bucket's **end**, so
    every observation is information that existed by its own timestamp.
    """
    s = pd.Series(
        cex["close"].astype(float).to_numpy(),
        index=pd.to_datetime(cex["second"].to_numpy(), unit="s", utc=True),
    ).sort_index()
    step = f"{sample_minutes}min"
    return s.resample(step, label="right", closed="right").last().dropna()


def realized_variance(
    prices: pd.Series, sample_minutes: int = 5, window_hours: int = 24
) -> pd.Series:
    """Trailing realized variance, annualised.

    Sum of squared log returns over the trailing window, scaled to a year. The
    window is closed on the right and the result is shifted by one sampling
    period, so the variance carried at time t uses only returns completed
    strictly before t. Without that shift the estimator peeks at the return it
    is about to be used to explain.
    """
    r = np.log(prices).diff()
    per_window = int(window_hours * 60 / sample_minutes)
    rv = r.pow(2).rolling(per_window, min_periods=per_window // 2).sum()
    annualised = rv * (SECONDS_PER_YEAR / (window_hours * 3600))
    return annualised.shift(1).rename("rv_annualised")


def bipower_variation(
    prices: pd.Series, sample_minutes: int = 5, window_hours: int = 24
) -> pd.Series:
    """Jump-robust estimator: mean of |r_t| * |r_{t-1}| over the window.

    Isolates the continuous component of quadratic variation. If sigma^2/8
    tracks empirical LVR better under bipower than under plain RV, that says
    jumps are not arbitraged the way the theory's diffusion assumes — a finding,
    not a nuisance.
    """
    r = np.log(prices).diff().abs()
    mu1 = np.sqrt(2 / np.pi)
    bp = (r * r.shift(1)) / (mu1**2)
    per_window = int(window_hours * 60 / sample_minutes)
    out = bp.rolling(per_window, min_periods=per_window // 2).sum()
    annualised = out * (SECONDS_PER_YEAR / (window_hours * 3600))
    return annualised.shift(1).rename("bipower_annualised")


def garman_klass(ohlc: pd.DataFrame, window_hours: int = 24) -> pd.Series:
    """Range-based estimator. More efficient per observation; sensitive to gaps."""
    hl = np.log(ohlc["high"].astype(float) / ohlc["low"].astype(float)) ** 2
    co = np.log(ohlc["close"].astype(float) / ohlc["open"].astype(float)) ** 2
    gk = 0.5 * hl - (2 * np.log(2) - 1) * co
    per_window = int(window_hours * 60)
    out = gk.rolling(per_window, min_periods=per_window // 2).sum()
    return (out * (SECONDS_PER_YEAR / (window_hours * 3600))).shift(1).rename("gk_annualised")


def align_to_blocks(vol: pd.Series, block_timestamps: pd.Series) -> pd.Series:
    """Attach the latest volatility estimate available at or before each block.

    Backward `merge_asof`, so no block ever sees an estimate stamped after it.
    """
    left = pd.DataFrame({"ts": pd.to_datetime(block_timestamps.astype("int64"), unit="s", utc=True)})
    right = pd.DataFrame({"ts": vol.index, "vol": vol.to_numpy()}).dropna()
    merged = pd.merge_asof(
        left.sort_values("ts"), right.sort_values("ts"), on="ts", direction="backward"
    )
    return merged["vol"]


def har_rv_forecast(rv: pd.Series, horizon_days: int = 7) -> pd.Series:
    """HAR-RV: daily, weekly and monthly realized variance components.

    The volatility forecast feeding the analytical arm of the H6 horse race.
    Fitted strictly on data available at t.
    """
    raise NotImplementedError("Stage 6.3 — H6 baseline")


def garch_forecast(returns: pd.Series, horizon_days: int = 7) -> pd.Series:
    """GARCH(1,1) alternative to HAR-RV, as a robustness arm."""
    raise NotImplementedError("Stage 6.3")
