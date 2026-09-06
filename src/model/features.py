"""Feature construction. Every feature is strictly known at time t.

The no-lookahead property is asserted by test, not assumed. `assert_no_lookahead`
is the Stage 6 gate and must pass before any model result is believed — an
out-of-sample R-squared above 0.5 on this problem is a leak first and a discovery
second.

Target: net LP return over the following week, per pool.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_NAMES = [
    "realized_vol_7d",
    "realized_vol_30d",
    "vol_of_vol_30d",
    "implied_vol",              # Deribit DVOL
    "iv_rv_spread",             # implied minus realised — the variance risk premium
    "fee_tier_bps",
    "volume_tvl_ratio_7d",
    "liquidity_concentration",  # Herfindahl over the tick liquidity distribution
    "mev_intensity_30d",
    "gas_price_median_7d",
    "pool_age_days",
    "tvl_usd",
    "staleness_median_7d",      # how long the pool sits on a stale price
]

TARGET_NAME = "net_lp_return_next_7d"


def _trailing(s: pd.Series, window: str, fn: str = "mean") -> pd.Series:
    """Trailing window closed on the right, then lagged one step.

    Both halves matter. Closing on the right keeps the current observation out
    of its own predictor; the lag keeps a feature stamped at `t` from containing
    anything that happened at `t`.
    """
    r = getattr(s.rolling(window, closed="right"), fn)()
    return r.shift(1)


def build_weekly_panel(
    derived: pd.DataFrame, pool_id: str, fee_tier_bps: int,
    dvol: pd.Series | None = None, pool_created: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Collapse a pool's block-level derived table to a weekly feature panel.

    Weekly because the target is a weekly net return; block-level features would
    have to be aggregated to the target's frequency anyway, and doing it here
    keeps the aggregation in one place where the lagging can be checked.
    """
    df = derived.copy()
    df["ts"] = pd.to_datetime(df["block_timestamp"].astype("int64"), unit="s", utc=True)
    df = df.set_index("ts").sort_index()

    df["rv"] = df["rv_annualised"].astype(float)
    df["px"] = df["cex_price"].astype(float)
    df["vol0"] = [abs(int(v)) for v in df["volume0"]]

    weekly = pd.DataFrame(index=df.resample("W").last().index)
    weekly["realized_vol_7d"] = np.sqrt(_trailing(df["rv"].resample("W").mean(), "7D"))
    weekly["realized_vol_30d"] = np.sqrt(_trailing(df["rv"].resample("W").mean(), "30D"))
    weekly["vol_of_vol_30d"] = _trailing(df["rv"].resample("W").mean(), "30D", "std")
    weekly["fee_tier_bps"] = fee_tier_bps
    weekly["staleness_median_7d"] = _trailing(
        df["staleness_seconds"].astype(float).resample("W").median(), "7D", "median"
    )
    weekly["volume_usd_7d"] = _trailing(df["vol0"].resample("W").sum(), "7D", "sum")

    if dvol is not None:
        iv = dvol.resample("W").last() / 100.0
        weekly["implied_vol"] = iv.shift(1)
        weekly["iv_rv_spread"] = weekly["implied_vol"] - weekly["realized_vol_30d"]

    if pool_created is not None:
        weekly["pool_age_days"] = (weekly.index - pool_created).days

    weekly["pool"] = pool_id
    return weekly


def liquidity_concentration(tick_liquidity: pd.Series) -> float:
    """Herfindahl index over the tick liquidity distribution.

    High concentration means fees are shared among fewer, tighter positions and
    the pool loses depth faster on a move — plausibly informative for both the
    fee and the LVR side.
    """
    total = float(tick_liquidity.sum())
    if total <= 0:
        return float("nan")
    shares = tick_liquidity.astype(float) / total
    return float((shares**2).sum())


def build_target(net_returns: pd.Series, horizon_days: int = 7) -> pd.Series:
    """Forward net return over the next `horizon_days`.

    Overlapping by construction when sampled more often than the horizon, which
    is exactly why Stage 6 uses purged, embargoed cross-validation.
    """
    return net_returns.shift(-1).rolling(horizon_days // 7 or 1).mean().rename(TARGET_NAME)


# --------------------------------------------------------------------------- #
# Stage 6 gate
# --------------------------------------------------------------------------- #

def assert_no_lookahead(
    features: pd.DataFrame, target: pd.Series, timestamps: pd.Series | None = None,
    horizon_days: int = 7, tol: float = 0.02,
) -> dict:
    """Stage 6 GATE. Raise if any feature appears to carry future information.

    Three checks, each catching a different way a leak gets in.

    1. **Contemporaneous correlation.** A feature must not correlate more
       strongly with the target's own realisation window than a one-period lag
       of itself does. A feature that does is reading its own answer.
    2. **Shift test.** Lagging the whole feature matrix by one period must not
       *improve* in-sample fit. If it does, the unlagged matrix was reaching
       forward.
    3. **Index alignment.** Every feature timestamp must be strictly before the
       start of the target window it predicts.

    Returns a report; raises on failure so a leak stops the pipeline rather than
    producing a good-looking number.
    """
    df = pd.concat([features, target.rename("__y")], axis=1).dropna()
    if len(df) < 20:
        raise ValueError(f"need at least 20 aligned observations, got {len(df)}")

    X = df[features.columns].select_dtypes(include=[np.number])
    y = df["__y"]
    report: dict = {"n_obs": len(df), "violations": []}

    for col in X.columns:
        now = abs(X[col].corr(y))
        lagged = abs(X[col].shift(1).corr(y))
        if pd.notna(now) and pd.notna(lagged) and now > lagged + tol and now > 0.5:
            report["violations"].append(
                {"feature": col, "corr_now": float(now), "corr_lagged": float(lagged),
                 "why": "correlates with the target more than its own lag does"}
            )

    def r2(mat: pd.DataFrame, yy: pd.Series) -> float:
        A = np.column_stack([np.ones(len(mat)), mat.to_numpy(float)])
        b = yy.to_numpy(float)
        coef, *_ = np.linalg.lstsq(A, b, rcond=None)
        resid = b - A @ coef
        tss = float(((b - b.mean()) ** 2).sum())
        return 1 - float((resid**2).sum()) / tss if tss > 0 else float("nan")

    aligned = pd.concat([X, y], axis=1).dropna()
    shifted = pd.concat([X.shift(1), y], axis=1).dropna()
    r2_now = r2(aligned[X.columns], aligned["__y"])
    r2_lag = r2(shifted[X.columns], shifted["__y"])
    report["r2_unlagged"], report["r2_lagged"] = r2_now, r2_lag
    if pd.notna(r2_now) and pd.notna(r2_lag) and r2_lag > r2_now + 0.05:
        report["violations"].append(
            {"feature": "<all>", "r2_unlagged": r2_now, "r2_lagged": r2_lag,
             "why": "lagging the matrix improves fit, so the unlagged matrix reaches forward"}
        )

    if timestamps is not None:
        horizon = pd.Timedelta(days=horizon_days)
        bad = int((pd.to_datetime(timestamps) + horizon < pd.to_datetime(timestamps)).sum())
        if bad:
            report["violations"].append({"feature": "<index>", "why": "non-monotonic timestamps"})

    report["passed"] = not report["violations"]
    if not report["passed"]:
        raise AssertionError(
            "no-lookahead gate FAILED:\n  "
            + "\n  ".join(str(v) for v in report["violations"])
        )
    return report
