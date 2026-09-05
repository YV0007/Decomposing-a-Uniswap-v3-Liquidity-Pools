"""Optimal fee tier as a function of volatility (open question 5).

The mechanism H4 tests: arbitrage only fires when the price gap exceeds the
fee, so a higher fee tier is a wider no-arbitrage band and less LVR per unit of
volatility — bought at the price of less uninformed volume.

If an interior optimum exists as a function of sigma, that is a clean
theoretical result, and it would predict which tier an LP should choose given a
volatility forecast. Validate against the H4 natural experiment.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd


def no_arbitrage_band(fee_rate: Decimal, gas_usd: Decimal, pool_value: Decimal) -> Decimal:
    """Width of the price gap that must open before arbitrage is profitable.

    Fee plus gas, expressed as a relative price move. This is the quantity that
    makes a higher tier a partial shield against LVR.
    """
    raise NotImplementedError("Stage 5.2 — open question 5")


def lvr_under_fee_band(sigma: Decimal, band: Decimal) -> Decimal:
    """LVR when arbitrage is suppressed until the gap exceeds `band`.

    The unrestricted sigma^2/8 result assumes frictionless continuous
    arbitrage. A fee band truncates the small moves, so this should sit strictly
    below sigma^2/8 and converge to it as the band goes to zero — a limit worth
    checking as a correctness test on the derivation.
    """
    raise NotImplementedError("Stage 5.2 — open question 5")


def optimal_fee_tier(sigma: Decimal, volume_elasticity: Decimal, available_tiers: list[int]) -> int:
    """Tier maximising expected net return at a given volatility.

    Requires an assumption about how uninformed volume responds to the fee.
    That elasticity is the weak link and must be estimated from the data or
    stated as an assumption with the result's sensitivity to it shown.
    """
    raise NotImplementedError("Stage 5.2 — open question 5")


def validate_against_h4(predicted: pd.DataFrame, observed: pd.DataFrame) -> dict:
    """Does the predicted tier ranking match the observed one at 5/30/100bp?"""
    raise NotImplementedError("Stage 5.2 — open question 5")
