"""Where to park LP capital. Not a buy/sell signal — an allocation decision.

Weekly: for each pool, predicted net return above threshold means PROVIDE;
weights proportional to predicted net, or equal-weight among qualifiers.

This is Output 2.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd


def allocation_signal(predictions: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Per-pool PROVIDE/AVOID with weights.

    Columns: `[timestamp, pool, predicted_fee_yield, predicted_lvr,
    predicted_mev, predicted_net, signal, weight]` — the decomposition is
    carried through to the signal so a reader can see *why* a pool is avoided,
    not just that it is.
    """
    raise NotImplementedError("Stage 7.1")


def normalise_weights(raw: pd.Series, scheme: str) -> pd.Series:
    """Weights summing to at most 1. An all-AVOID week means holding cash."""
    raise NotImplementedError("Stage 7.1")
