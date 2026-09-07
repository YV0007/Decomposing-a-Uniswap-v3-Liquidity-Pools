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


# --------------------------------------------------------------------------- #
# Forecasts — the analytical arm of the H6 horse race
# --------------------------------------------------------------------------- #

def har_components(rv_daily: pd.Series) -> pd.DataFrame:
    """Daily, weekly and monthly realized-variance components.

    Corsi's HAR: today's variance, the trailing 5-day mean, and the trailing
    22-day mean. Each is computed on data up to and including `t`, and the
    regression predicts `t+1` onward — so no component may include the period it
    is used to forecast.
    """
    return pd.DataFrame(
        {
            "rv_d": rv_daily,
            "rv_w": rv_daily.rolling(5, min_periods=3).mean(),
            "rv_m": rv_daily.rolling(22, min_periods=10).mean(),
        }
    )


# --------------------------------------------------------------------------- #
# Daily realised measures — the inputs the better HAR variants need
# --------------------------------------------------------------------------- #

def daily_realised_measures(prices: pd.Series, sample_minutes: int = 5) -> pd.DataFrame:
    """Daily realised variance, bipower variation, quarticity and jump component.

    HAR-RV treats every daily variance observation as equally informative. It is
    not: a day's realised variance is itself estimated with error, and that error
    grows with **realised quarticity**. HAR-Q uses `sqrt(RQ)` to discount noisy
    observations, which is the single most-cited improvement on HAR.

    Separately, `RV − BV` isolates the jump component. `sigma^2/8` is derived
    under a diffusion, so if the continuous part forecasts LVR better than total
    variance does, that is direct evidence about which part of price movement
    arbitrageurs actually extract from.

    Columns: `rv` (realised variance), `bv` (bipower, jump-robust), `rq`
    (quarticity), `jump` (max(rv − bv, 0)), all daily and *not* annualised —
    annualisation happens once, downstream.
    """
    r = np.log(prices).diff().dropna()
    per_day = int(24 * 60 / sample_minutes)
    mu1 = np.sqrt(2 / np.pi)

    g = r.groupby(r.index.floor("D"))
    rv = g.apply(lambda x: float((x**2).sum()))
    bv = g.apply(lambda x: float((x.abs() * x.abs().shift(1)).sum()) / (mu1**2))
    # Realised quarticity, Barndorff-Nielsen & Shephard: (n/3) * sum(r^4)
    rq = g.apply(lambda x: float(len(x) / 3 * (x**4).sum()))
    n = g.size()

    out = pd.DataFrame({"rv": rv, "bv": bv, "rq": rq, "n_obs": n})
    # Days with far too few observations are estimation noise, not low variance.
    out = out[out["n_obs"] >= per_day // 2]
    out["jump"] = (out["rv"] - out["bv"]).clip(lower=0.0)
    out["bv"] = out["bv"].clip(lower=0.0)
    return out


def _har_design(measures: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Regressors for one HAR variant, all computed from data up to and including t."""
    rv = measures["rv"]
    X = pd.DataFrame({
        "rv_d": rv,
        "rv_w": rv.rolling(5, min_periods=3).mean(),
        "rv_m": rv.rolling(22, min_periods=10).mean(),
    })
    if kind == "har":
        return X
    if kind == "harq":
        # Interaction with sqrt(RQ): the daily term is discounted on days when
        # the variance estimate itself is imprecise.
        X["rv_d_q"] = X["rv_d"] * np.sqrt(measures["rq"].clip(lower=0))
        return X
    if kind == "harcj":
        # Continuous and jump components enter separately.
        bv = measures["bv"]
        X = pd.DataFrame({
            "c_d": bv,
            "c_w": bv.rolling(5, min_periods=3).mean(),
            "c_m": bv.rolling(22, min_periods=10).mean(),
            "j_d": measures["jump"],
            "j_w": measures["jump"].rolling(5, min_periods=3).mean(),
        })
        return X
    raise ValueError(f"unknown HAR variant {kind!r}")


def har_family_forecast(
    measures: pd.DataFrame, kind: str = "har", horizon_days: int = 7,
    min_train: int = 60, extra: pd.DataFrame | None = None,
) -> pd.Series:
    """Expanding-window forecast of mean variance over the next `horizon_days`.

    Refit at every step on data strictly before the origin, and the horizon is
    **purged** from the training set: a label stamped at `t'` covers
    `(t', t' + horizon]`, so within `horizon` of the origin it is not yet
    knowable. Training on it is the same leak purged cross-validation exists to
    close, and it lives inside the forecast too.

    `extra` adds exogenous regressors — implied volatility, for instance — with
    the same lagging discipline.
    """
    X = _har_design(measures, kind)
    if extra is not None:
        X = X.join(extra, how="left")
    rv = measures["rv"]
    y = rv.shift(-1).rolling(horizon_days, min_periods=1).mean().shift(-(horizon_days - 1))

    out = pd.Series(index=rv.index, dtype=float)
    valid = X.dropna().index
    for i, t in enumerate(valid):
        if i < min_train + horizon_days:
            continue
        train = valid[: max(0, i - horizon_days)]
        xtr, ytr = X.loc[train], y.loc[train]
        m = ytr.notna() & xtr.notna().all(axis=1)
        if int(m.sum()) < min_train:
            continue
        A = np.column_stack([np.ones(int(m.sum())), xtr[m].to_numpy(float)])
        try:
            coef, *_ = np.linalg.lstsq(A, ytr[m].to_numpy(float), rcond=None)
        except np.linalg.LinAlgError:
            continue
        out.loc[t] = float(coef @ np.concatenate([[1.0], X.loc[t].to_numpy(float)]))
    return out.clip(lower=0.0).rename(f"{kind}_{horizon_days}d")


def har_rv_forecast(
    rv_daily: pd.Series, horizon_days: int = 7, min_train: int = 60
) -> pd.Series:
    """Expanding-window HAR-RV forecast of average variance over the next `h` days.

    The analytical arm of H6. Refit at every step on data strictly before the
    forecast origin, so the series is usable out of sample without any further
    purging — a single fit over the whole sample would leak the future into
    every earlier prediction.

    Returns the forecast indexed by the origin date: the value at `t` is the
    prediction for `(t, t + horizon]`.
    """
    import numpy as np

    rv = pd.Series(rv_daily).dropna()
    X = har_components(rv)
    # Target: mean variance over the next `horizon_days`, known only later.
    y = rv.shift(-1).rolling(horizon_days, min_periods=1).mean().shift(-(horizon_days - 1))

    out = pd.Series(index=rv.index, dtype=float)
    valid = X.dropna().index
    for i, t in enumerate(valid):
        if i < min_train + horizon_days:
            continue
        # Purge the horizon. A training label stamped at t' covers
        # (t', t' + horizon], so for t' within `horizon` of the forecast origin
        # that window reaches past t and the label is not yet knowable. Training
        # on it is a leak — the same one purged cross-validation exists to close,
        # and it lives inside the forecast too.
        train_idx = valid[: max(0, i - horizon_days)]
        xtr = X.loc[train_idx]
        ytr = y.loc[train_idx]
        mask = ytr.notna()
        if mask.sum() < min_train:
            continue
        A = np.column_stack([np.ones(int(mask.sum())), xtr[mask].to_numpy(float)])
        b = ytr[mask].to_numpy(float)
        try:
            coef, *_ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            continue
        out.loc[t] = float(coef @ np.concatenate([[1.0], X.loc[t].to_numpy(float)]))
    return out.rename(f"har_rv_{horizon_days}d")


def ewma_forecast(rv_daily: pd.Series, lam: float = 0.94) -> pd.Series:
    """RiskMetrics EWMA variance. One parameter, no fitting, hard to overfit.

    Included as the honest floor for the analytical arm: if HAR-RV cannot beat a
    single fixed decay constant, the extra structure is not earning its place.
    """
    rv = pd.Series(rv_daily).dropna()
    return rv.ewm(alpha=1 - lam, adjust=False).mean().shift(1).rename("ewma_rv")


def garch_forecast(
    returns: pd.Series, horizon_days: int = 7, min_train: int = 250
) -> pd.Series:
    """GARCH(1,1) forecast of average variance over the next `h` days.

    Fitted by Gaussian quasi-maximum likelihood. Refit on an expanding window,
    like HAR, for the same reason.

    The multi-step forecast uses the analytic mean-reversion of GARCH toward its
    unconditional variance rather than simulating paths:
    `E[sigma^2_{t+k}] = w/(1-a-b) + (a+b)^(k-1) (sigma^2_{t+1} - w/(1-a-b))`.
    """
    import numpy as np
    from scipy.optimize import minimize

    r = pd.Series(returns).dropna()
    out = pd.Series(index=r.index, dtype=float)

    def nll(params, x):
        w, a, b = params
        if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
            return 1e10
        var = np.empty(len(x))
        var[0] = x.var()
        for i in range(1, len(x)):
            var[i] = w + a * x[i - 1] ** 2 + b * var[i - 1]
        return 0.5 * np.sum(np.log(var) + x**2 / var)

    for i in range(min_train, len(r)):
        x = r.iloc[:i].to_numpy(float)
        v0 = x.var()
        res = minimize(nll, [v0 * 0.05, 0.08, 0.90], args=(x,), method="Nelder-Mead",
                       options={"maxiter": 400, "xatol": 1e-8, "fatol": 1e-8})
        w, a, b = res.x
        if not (w > 0 and a >= 0 and b >= 0 and a + b < 0.999):
            continue
        var = v0
        for j in range(1, len(x)):
            var = w + a * x[j - 1] ** 2 + b * var
        next_var = w + a * x[-1] ** 2 + b * var
        uncond = w / (1 - a - b)
        total = sum(uncond + (a + b) ** (k - 1) * (next_var - uncond)
                    for k in range(1, horizon_days + 1))
        out.iloc[i] = total / horizon_days * 365          # annualise a daily variance
    return out.rename(f"garch_{horizon_days}d")
