"""Optimal v3 range width — the original mathematics (Stage 8, appendix).

Narrower range means more fees per dollar deployed, more LVR per dollar, and a
higher probability of falling out of range on a move. There is a trade-off, so
there is an optimum.

    maximise over half-width w:   E[fees(w)] - E[LVR(w)] - E[recentring_cost(w)]

under GBM with volatility sigma, fee tier f, and a re-centring cost.

Open question 6: closed form or numerical. Either answer is publishable; a
closed form is better. Validate the theoretical optimum against the empirical
optimum from the `position.sweeps` range-width sweep.
"""

from __future__ import annotations

from decimal import Decimal


def expected_fees(w: Decimal, sigma: Decimal, fee_rate: Decimal, volume_rate: Decimal) -> Decimal:
    """Expected fee income as a function of half-width.

    Two competing effects: concentration raises the fee share per dollar while
    in range, and narrowing lowers the fraction of time spent in range.
    """
    raise NotImplementedError("Stage 8")


def expected_lvr(w: Decimal, sigma: Decimal) -> Decimal:
    """Expected LVR as a function of half-width.

    The sigma^2/8 result is for a full-range constant-product pool; the
    concentrated case scales with the leverage that concentration implies,
    which is the term this function has to get right.
    """
    raise NotImplementedError("Stage 8")


def expected_recentring_cost(w: Decimal, sigma: Decimal, gas_usd: Decimal) -> Decimal:
    """Expected re-centring cost — exit frequency times gas.

    Exit frequency under GBM is a first-passage problem for the log price
    leaving a symmetric band.
    """
    raise NotImplementedError("Stage 8")


def optimal_half_width(sigma: Decimal, fee_rate: Decimal, gas_usd: Decimal, volume_rate: Decimal):
    """Solve for w*. Closed form if one exists, numerical otherwise."""
    raise NotImplementedError("Stage 8 — open question 6")


def validate_against_empirical(theoretical_w, empirical_sweep) -> dict:
    """Does the derived optimum match the optimum observed in the sweep?

    A theoretical result that does not survive this comparison is reported with
    the gap, not quietly dropped.
    """
    raise NotImplementedError("Stage 8")
