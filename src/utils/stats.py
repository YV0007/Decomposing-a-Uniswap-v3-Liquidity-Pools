"""Statistical machinery held to the standards in section 9 of the spec.

Every estimate reported in the paper carries a confidence interval, every
regression on overlapping data uses Newey-West standard errors, and every
Sharpe ratio is reported deflated alongside its raw value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OLSResult:
    """Regression output with the fields H3 requires."""

    alpha: float
    beta: float
    alpha_se: float
    beta_se: float
    alpha_t: float
    beta_t: float
    r_squared: float
    n_obs: int
    nw_lags: int
    residuals: np.ndarray

    def beta_ci(self, level: float = 0.95) -> tuple[float, float]:
        raise NotImplementedError("Stage 3.3")


def newey_west_ols(y: pd.Series, x: pd.Series, lags: int | None = None) -> OLSResult:
    """Univariate OLS with Newey-West HAC standard errors.

    Used for H3: ``empirical_LVR = alpha + beta * analytical_LVR + eps``, where
    the prediction is beta ~ 1 and alpha ~ 0. Overlapping windows in the
    volatility estimator induce serial correlation in the residuals, so plain
    OLS standard errors would overstate the precision of beta.

    `lags` defaults to the Newey-West rule of thumb, ``floor(4*(n/100)**(2/9))``.
    """
    raise NotImplementedError("Stage 3.3 — H3 regression")


def deflated_sharpe_ratio(
    returns: pd.Series,
    n_trials: int,
    benchmark_sharpe: float = 0.0,
) -> dict[str, float]:
    """Bailey & Lopez de Prado deflated Sharpe.

    `n_trials` must come from :func:`src.utils.speclog.count_specifications`,
    not from a guess. Deflating by a number smaller than the true search is
    worse than not deflating at all, because it looks rigorous.

    Returns the raw Sharpe, the deflated Sharpe, the probabilistic Sharpe
    ratio, and the skew/kurtosis adjustments that produced it.
    """
    raise NotImplementedError("Stage 7.2")


def block_bootstrap_ci(
    series: pd.Series,
    statistic,
    block_size: int,
    n_boot: int = 1000,
    level: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float]:
    """Circular block bootstrap CI, preserving serial dependence.

    The default interval for any statistic computed on a time series here —
    LVR totals, net returns, decomposition components.
    """
    raise NotImplementedError("Stage 5.3")


def summary_with_ci(series: pd.Series, **kwargs) -> pd.Series:
    """Mean, CI bounds and n, for direct insertion into an output table."""
    raise NotImplementedError("Stage 5.3")
