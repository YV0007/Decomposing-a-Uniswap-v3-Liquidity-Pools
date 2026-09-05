"""LVR correctness.

The load-bearing test is :func:`test_analytical_reduces_to_sigma_squared_over_8`.
The `sigma^2 / 8` result is stated for a *full-range* constant-product pool; the
implementation here differentiates the position's own amount function so it also
handles a concentrated range. If that generalisation is right, it must collapse
back to the textbook constant in the full-range limit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.build.lvr import (analytical_lvr_rate, lvr_from_cex_path, lvr_from_pool_path,
                           naive_v2_lvr_rate, realised_extraction, value_at_external)
from src.build.position import Position, open_position
from src.utils import precision as pr
from src.utils.config import pool

SPEC = pool("ETH_USDC_30bp")
S0 = Decimal("1200")
SIGMA = Decimal("0.60")           # 60% annualised, typical for ETH

#: Widest range on a spacing-60 pool. Uniswap's own full-range bounds.
FULL_LOWER, FULL_UPPER = -887220, 887220


def _sqrt(price: Decimal) -> int:
    return pr.price_to_sqrt_price_x96(price, 6, 18, invert=True)


def _position(half_width="0.10") -> Position:
    return open_position(SPEC, 1, _sqrt(S0), S0, Decimal("100000"), Decimal(half_width))


def _full_range_position(notional=Decimal("100000")) -> Position:
    probe = Position("full", 1, _sqrt(S0), FULL_LOWER, FULL_UPPER, 10**18, Decimal(0))
    v = value_at_external(probe, _sqrt(S0), S0, SPEC)
    return Position("full", 1, _sqrt(S0), FULL_LOWER, FULL_UPPER,
                    int(Decimal(10**18) * notional / v), notional)


# --------------------------------------------------------------------------- #
# The theoretical anchor
# --------------------------------------------------------------------------- #

def test_analytical_reduces_to_sigma_squared_over_8():
    """Full-range v3 is constant product, so the general form must give sigma^2 V/8."""
    pos = _full_range_position()
    v = value_at_external(pos, _sqrt(S0), S0, SPEC)
    general = analytical_lvr_rate(pos, SPEC, S0, SIGMA)
    textbook = naive_v2_lvr_rate(v, SIGMA)
    rel = abs(general - textbook) / textbook
    assert rel < Decimal("0.001"), f"full-range limit off by {rel:.4%}"


def test_concentration_amplifies_lvr():
    """A tighter range carries more LVR per dollar deployed.

    This is the mechanism behind the whole v3 trade-off: concentration buys fee
    share and pays for it in adverse selection. Applying the full-range
    sigma^2 V/8 to a concentrated position understates the cost.
    """
    wide = analytical_lvr_rate(_position("0.50"), SPEC, S0, SIGMA)
    narrow = analytical_lvr_rate(_position("0.05"), SPEC, S0, SIGMA)
    assert narrow > wide * 2

    tight = _position("0.05")
    v = value_at_external(tight, _sqrt(S0), S0, SPEC)
    assert analytical_lvr_rate(tight, SPEC, S0, SIGMA) > naive_v2_lvr_rate(v, SIGMA)


def test_lvr_vanishes_outside_the_range():
    """Out of range the position is single-sided; its delta stops responding."""
    pos = _position("0.10")
    far = S0 * Decimal("3")
    assert analytical_lvr_rate(pos, SPEC, far, SIGMA) == 0


def test_lvr_scales_with_variance_not_volatility():
    pos = _position()
    a = analytical_lvr_rate(pos, SPEC, S0, Decimal("0.30"))
    b = analytical_lvr_rate(pos, SPEC, S0, Decimal("0.60"))
    assert b / a == pytest.approx(4, rel=1e-9)


# --------------------------------------------------------------------------- #
# Empirical measures
# --------------------------------------------------------------------------- #

def test_cex_path_lvr_is_never_negative():
    """Marking AMM holdings at any price other than the one that produced them
    can only cost the LP, so the perfect-arbitrage measure is non-negative."""
    pos = _position("0.20")
    for a, b in ((S0, S0 * Decimal("1.01")), (S0, S0 * Decimal("0.99")), (S0, S0)):
        assert lvr_from_cex_path(pos, SPEC, a, b) >= 0


def test_cex_path_lvr_is_zero_when_the_external_price_does_not_move():
    pos = _position()
    assert lvr_from_cex_path(pos, SPEC, S0, S0) == 0


def test_pool_path_lvr_is_zero_when_the_pool_does_not_move():
    """No pool movement means no value transferred, so a persistent dislocation
    is not counted again on every block."""
    pos = _position()
    s = _sqrt(S0)
    assert lvr_from_pool_path(pos, SPEC, s, s, S0 * Decimal("1.02")) == 0


def test_pool_path_lvr_is_positive_when_the_pool_moves_toward_the_cex_price():
    """The arbitrage case: the pool is stale low and gets corrected upward."""
    pos = _position("0.20")
    cex = S0 * Decimal("1.02")
    got = lvr_from_pool_path(pos, SPEC, _sqrt(S0), _sqrt(cex), cex)
    assert got > 0


def test_pool_path_lvr_is_negative_when_the_pool_moves_away():
    """Uninformed flow pushing the pool away from the external price pays the LP.

    This asymmetry is the point of the paper: the same mechanism that loses to
    arbitrageurs earns from retail.
    """
    pos = _position("0.20")
    cex = S0
    got = lvr_from_pool_path(pos, SPEC, _sqrt(S0), _sqrt(S0 * Decimal("1.02")), cex)
    assert got < 0


def test_realised_extraction_is_floored_at_zero():
    """Arbitrage does not fire when the dislocation is under fee plus gas."""
    assert realised_extraction(Decimal("5"), Decimal("10000"), Decimal("0.003"), Decimal("20")) == 0
    assert realised_extraction(Decimal("500"), Decimal("10000"), Decimal("0.003"), Decimal("20")) > 0


def test_extraction_is_strictly_below_gross_lvr():
    """LVR is gross adverse selection; extraction is what survives frictions."""
    gross = Decimal("500")
    net = realised_extraction(gross, Decimal("10000"), Decimal("0.003"), Decimal("20"))
    assert 0 < net < gross
