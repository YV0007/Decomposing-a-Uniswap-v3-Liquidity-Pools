"""Delta hedge for the primary (delta-hedged) variant.

Raw LP return is dominated by whether ETH went up. Hedging strips the
directional beta and leaves the market-making return the paper is about:
``fees - LVR - MEV - funding``.

Specification is fixed in DECISIONS.md 0.1: Binance ETH perpetual, daily
rebalance baseline, realised funding, hedge ratio from the v3 position delta —
**not** 0.5.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd


def hedge_schedule(position_delta: pd.Series, freq: str = "1D") -> pd.DataFrame:
    """Target short size at each rebalance point.

    The hedge tracks the v3 position's delta, which sweeps from fully-risky to
    fully-cash as price crosses the range. A constant 0.5 hedge would leave a
    residual that grows precisely when the position is most stressed.
    """
    raise NotImplementedError("Stage 0.1 / 5.1")


def funding_cost(hedge: pd.DataFrame, funding_rates: pd.DataFrame) -> pd.Series:
    """Realised funding paid or received on the perpetual leg.

    Actual realised funding, per the Stage 0 decision. Funding is a first-order
    cost of the hedged variant and is never assumed.
    """
    raise NotImplementedError("Stage 5.1")


def hedge_pnl(hedge: pd.DataFrame, perp_price: pd.Series) -> pd.Series:
    """Mark-to-market P&L of the perpetual leg, net of funding."""
    raise NotImplementedError("Stage 5.1")


def hedging_error(
    position_delta: pd.Series, hedge: pd.DataFrame, price: pd.Series
) -> pd.Series:
    """Unhedged residual between rebalances.

    Open question 7. If this residual is large relative to the LVR being
    measured, the delta-hedged variant stops being the cleaner one and the
    Stage 0.1 decision has to be revisited — which is why it is measured rather
    than assumed away.
    """
    raise NotImplementedError("Stage 0.1 — open question 7")


def rebalance_frequency_sweep(
    position_delta: pd.Series, price: pd.Series, funding: pd.DataFrame,
    freqs: list[str] = ["1h", "1D", "7D"],
) -> pd.DataFrame:
    """Hedging error and funding cost against rebalance frequency.

    The trade-off is hedging error against gas and funding turnover; the sweep
    is what closes open question 7.
    """
    raise NotImplementedError("Stage 0.1 — open question 7")
