"""Feature construction. Every feature is strictly known at time t.

The no-lookahead property is asserted by test, not assumed. `assert_no_lookahead`
is the Stage 6 gate and must pass before any model result is believed.

Target: net LP return over the following week, per pool.
"""

from __future__ import annotations

import pandas as pd

FEATURE_NAMES = [
    "realized_vol_7d",
    "realized_vol_30d",
    "implied_vol",            # Deribit DVOL as proxy
    "fee_tier",
    "volume_tvl_ratio_7d",
    "liquidity_concentration",  # Herfindahl over ticks
    "mev_intensity_30d",
    "gas_price_median_7d",
    "pool_age_days",
    "tvl_usd",
    "vol_of_vol",
]

TARGET_NAME = "net_lp_return_next_7d"


def build_features(pool_state: pd.DataFrame, decomposition: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Assemble the feature matrix. Every column is lagged to be known at t."""
    raise NotImplementedError("Stage 6.1")


def liquidity_concentration(tick_map: pd.DataFrame) -> pd.Series:
    """Herfindahl index over the tick liquidity distribution.

    High concentration means fees are shared among fewer, tighter positions and
    that the pool falls out of depth faster on a move — plausibly informative
    for both the fee and the LVR side.
    """
    raise NotImplementedError("Stage 6.1")


def build_target(decomposition: pd.DataFrame, horizon_days: int = 7) -> pd.Series:
    """Forward net return. Overlapping by construction — hence purged CV."""
    raise NotImplementedError("Stage 6.1")


def assert_no_lookahead(features: pd.DataFrame, target: pd.Series, timestamps: pd.Series) -> None:
    """Stage 6 GATE. Raise if any feature uses information after its timestamp.

    Checks, per feature: shifting the whole feature matrix back one period must
    not improve in-sample fit; no feature may correlate with the target's own
    realisation window more strongly than with its history; every rolling
    window must be closed on the right.

    An out-of-sample R-squared above 0.5 on this problem is a lookahead symptom
    first and a discovery second. Find it before believing it.
    """
    raise NotImplementedError("Stage 6.1 — GATE")
