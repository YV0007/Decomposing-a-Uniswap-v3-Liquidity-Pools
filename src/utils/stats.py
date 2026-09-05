"""Statistical machinery held to the standards in section 9 of the spec.

Every estimate reported carries a confidence interval, every regression on
overlapping data uses Newey-West standard errors, and every Sharpe ratio is
reported deflated alongside its raw value.

Implemented directly rather than delegated, so the assumptions are visible and
testable — these are the numbers the paper's claims rest on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sps

EULER_MASCHERONI = 0.5772156649015329


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
        z = sps.norm.ppf(0.5 + level / 2)
        return self.beta - z * self.beta_se, self.beta + z * self.beta_se

    def beta_equals(self, value: float = 1.0) -> float:
        """Two-sided p-value for `beta == value`. H3 predicts beta = 1."""
        if self.beta_se == 0:
            return float("nan")
        return float(2 * (1 - sps.norm.cdf(abs(self.beta - value) / self.beta_se)))


def newey_west_lags(n: int) -> int:
    """Newey-West rule of thumb: `floor(4 * (n/100) ** (2/9))`."""
    return max(1, int(math.floor(4 * (n / 100) ** (2 / 9))))


def newey_west_ols(y: pd.Series, x: pd.Series, lags: int | None = None) -> OLSResult:
    """Univariate OLS with Newey-West HAC standard errors.

    Used for H3: `empirical_LVR = alpha + beta * analytical_LVR + eps`, where
    the prediction is beta ~ 1 and alpha ~ 0. Overlapping windows in the
    volatility estimator induce serial correlation in the residuals, so plain
    OLS standard errors would overstate the precision of beta — which on this
    question is the difference between "the theory holds" and "we cannot tell".
    """
    df = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(df) < 3:
        raise ValueError(f"need at least 3 paired observations, got {len(df)}")
    yv, xv = df["y"].to_numpy(float), df["x"].to_numpy(float)
    n = len(yv)
    lags = newey_west_lags(n) if lags is None else lags

    X = np.column_stack([np.ones(n), xv])
    xtx_inv = np.linalg.inv(X.T @ X)
    coef = xtx_inv @ X.T @ yv
    resid = yv - X @ coef

    # HAC meat matrix, Bartlett kernel.
    s = (X * resid[:, None]).T @ (X * resid[:, None])
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        a = (X[lag:] * resid[lag:, None]).T @ (X[:-lag] * resid[:-lag, None])
        s += w * (a + a.T)
    cov = xtx_inv @ s @ xtx_inv
    se = np.sqrt(np.diag(cov))

    tss = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - float((resid**2).sum()) / tss if tss > 0 else float("nan")

    return OLSResult(
        alpha=float(coef[0]), beta=float(coef[1]),
        alpha_se=float(se[0]), beta_se=float(se[1]),
        alpha_t=float(coef[0] / se[0]) if se[0] else float("nan"),
        beta_t=float(coef[1] / se[1]) if se[1] else float("nan"),
        r_squared=r2, n_obs=n, nw_lags=lags, residuals=resid,
    )


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe under the null that every trial has zero skill.

    The benchmark a strategy must beat to be more than the best of `n_trials`
    coin flips. Grows with the number of specifications searched, which is why
    the trial count has to be honest.
    """
    if n_trials < 2:
        return 0.0
    g = EULER_MASCHERONI
    a = sps.norm.ppf(1 - 1 / n_trials)
    b = sps.norm.ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * ((1 - g) * a + g * b)


def deflated_sharpe_ratio(
    returns: pd.Series, n_trials: int, periods_per_year: int = 52,
    sharpe_variance: float | None = None,
) -> dict:
    """Bailey & Lopez de Prado deflated Sharpe.

    `n_trials` must come from `src.utils.speclog.count_specifications`, not from
    a guess. Deflating by a number smaller than the true search is worse than
    not deflating at all, because it looks rigorous.

    The deflation adjusts for three things at once: the number of trials, the
    skew of the return distribution, and its kurtosis. A strategy with negative
    skew and fat tails needs a higher raw Sharpe to clear the same bar.
    """
    r = pd.Series(returns).dropna().to_numpy(float)
    n = len(r)
    if n < 4:
        raise ValueError(f"need at least 4 return observations, got {n}")
    sd = r.std(ddof=1)
    if sd == 0:
        raise ValueError("returns have zero variance")

    sr = r.mean() / sd
    skew = float(sps.skew(r))
    kurt = float(sps.kurtosis(r, fisher=False))

    if sharpe_variance is None:
        sharpe_variance = (1 - skew * sr + (kurt - 1) / 4 * sr**2) / max(1, n - 1)
    sr0 = expected_max_sharpe(n_trials, sharpe_variance)

    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    dsr = float(sps.norm.cdf((sr - sr0) * math.sqrt(n - 1) / denom))
    psr = float(sps.norm.cdf(sr * math.sqrt(n - 1) / denom))

    ann = math.sqrt(periods_per_year)
    return {
        "sharpe": sr * ann,
        "sharpe_per_period": sr,
        "deflated_sharpe_prob": dsr,
        "probabilistic_sharpe_prob": psr,
        "expected_max_sharpe_null": sr0 * ann,
        "n_trials": n_trials,
        "n_obs": n,
        "skew": skew,
        "kurtosis": kurt,
        "beats_null": dsr > 0.95,
    }


def block_bootstrap_ci(
    series: pd.Series, statistic=np.mean, block_size: int = 20,
    n_boot: int = 1000, level: float = 0.95, seed: int | None = 42,
) -> tuple[float, float]:
    """Circular block bootstrap CI, preserving serial dependence.

    The default interval for any statistic computed on a time series here. An
    i.i.d. bootstrap would give intervals far too narrow on data this
    autocorrelated.
    """
    x = pd.Series(series).dropna().to_numpy(float)
    n = len(x)
    if n < block_size:
        raise ValueError(f"series shorter ({n}) than the block size ({block_size})")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    doubled = np.concatenate([x, x])

    stats_ = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        sample = np.concatenate([doubled[s : s + block_size] for s in starts])[:n]
        stats_[i] = statistic(sample)
    lo = float(np.quantile(stats_, (1 - level) / 2))
    hi = float(np.quantile(stats_, 1 - (1 - level) / 2))
    return lo, hi


def summary_with_ci(series: pd.Series, **kwargs) -> pd.Series:
    """Mean, CI bounds and n, for direct insertion into an output table."""
    lo, hi = block_bootstrap_ci(series, **kwargs)
    s = pd.Series(series).dropna()
    return pd.Series({"mean": float(s.mean()), "ci_low": lo, "ci_high": hi, "n": int(len(s))})
