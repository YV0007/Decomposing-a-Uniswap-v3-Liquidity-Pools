"""Optimal range width — the closed form and its constraints.

The central claim is that concentration is *sign-neutral*: fees and LVR both
scale as 1/delta, so range width sets the scale of the outcome but never its
sign. Confirmed empirically on ETH/USDC 30bp, January 2023, where the fee/LVR
ratio moved 1.85% across a 34x span of widths.
"""

from __future__ import annotations

import math

import pytest

from src.theory.range_width import (calibrate_fee_coefficient, capacity_limit_usd,
                                    fee_rate, fee_rate_saturating,
                                    half_width_from_prices, kappa, lvr_rate, net_rate,
                                    optimal_half_width, optimal_half_width_numerical,
                                    recentre_rate, saturation_half_width,
                                    tick_spacing_half_width)

SIGMA, GAS_OVER_VALUE = 0.2866, 22.39 / 100_000
F_PROFITABLE = calibrate_fee_coefficient(0.2100, 0.1020)


# --------------------------------------------------------------------------- #
# The central claim
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("delta", [0.01, 0.05, 0.10, 0.25, 0.50])
def test_fees_and_lvr_share_the_same_scaling(delta):
    """Both go as 1/delta, so their ratio is invariant to width."""
    ratio = fee_rate(delta, F_PROFITABLE) / lvr_rate(delta, SIGMA)
    reference = fee_rate(0.1, F_PROFITABLE) / lvr_rate(0.1, SIGMA)
    assert ratio == pytest.approx(reference, rel=1e-12)


def test_concentration_cannot_change_the_sign_of_profitability():
    """No width rescues a pool where fees do not cover LVR.

    This is the result that matters for an LP: the choice of range is not a way
    out of an unprofitable pool, only a way to scale the outcome.
    """
    unprofitable = calibrate_fee_coefficient(0.05, 0.10)   # F well below sigma^2/4
    assert kappa(unprofitable, SIGMA) < 0
    for delta in (0.01, 0.05, 0.2, 1.0):
        gross = fee_rate(delta, unprofitable) - lvr_rate(delta, SIGMA)
        assert gross < 0


def test_losses_shrink_monotonically_with_width_when_unprofitable():
    """The corner solution: when kappa < 0 the least-bad position is the widest.

    Matches the empirical sweep, where net rose monotonically from -60.1% at
    +/-1% to -1.9% at +/-40%.
    """
    unprofitable = calibrate_fee_coefficient(0.05, 0.10)
    nets = [net_rate(d, unprofitable, SIGMA, GAS_OVER_VALUE)
            for d in (0.01, 0.03, 0.05, 0.10, 0.25, 0.40)]
    assert nets == sorted(nets)
    assert all(n < 0 for n in nets)


# --------------------------------------------------------------------------- #
# The closed form
# --------------------------------------------------------------------------- #

def test_closed_form_matches_a_grid_search():
    """A derivation and its implementation can be wrong together; a grid search
    over the same objective cannot repeat the algebra mistake."""
    s = optimal_half_width(F_PROFITABLE, SIGMA, GAS_OVER_VALUE)
    d_num, v_num = optimal_half_width_numerical(F_PROFITABLE, SIGMA, GAS_OVER_VALUE)
    assert s.optimal_half_width == pytest.approx(d_num, rel=1e-3)
    assert s.optimal_net_rate == pytest.approx(v_num, rel=1e-3)


def test_the_optimum_is_a_maximum():
    s = optimal_half_width(F_PROFITABLE, SIGMA, GAS_OVER_VALUE)
    d = s.optimal_half_width
    here = net_rate(d, F_PROFITABLE, SIGMA, GAS_OVER_VALUE)
    for eps in (0.8, 0.9, 1.1, 1.25):
        assert net_rate(d * eps, F_PROFITABLE, SIGMA, GAS_OVER_VALUE) < here


def test_no_optimum_when_fees_do_not_cover_lvr():
    s = optimal_half_width(calibrate_fee_coefficient(0.05, 0.10), SIGMA, GAS_OVER_VALUE)
    assert not s.profitable
    assert s.optimal_half_width is None
    assert "does not cover" in s.note


@pytest.mark.parametrize("field,factor,direction", [
    ("gas", 2.0, "wider"),
    ("sigma", 1.5, "wider"),
])
def test_comparative_statics(field, factor, direction):
    """delta* widens with gas and with volatility."""
    base = optimal_half_width(F_PROFITABLE, SIGMA, GAS_OVER_VALUE)
    if field == "gas":
        alt = optimal_half_width(F_PROFITABLE, SIGMA, GAS_OVER_VALUE * factor)
    else:
        alt = optimal_half_width(F_PROFITABLE * factor**2, SIGMA * factor, GAS_OVER_VALUE)
    assert alt.optimal_half_width > base.optimal_half_width


# --------------------------------------------------------------------------- #
# The two floors
# --------------------------------------------------------------------------- #

def test_tick_grid_clips_an_unrealisably_narrow_optimum():
    """When the economics want a range the pool cannot express, the LP is at a
    corner and the grid, not the economics, sets the position."""
    generous = calibrate_fee_coefficient(2.0, 0.10)      # very large fee margin
    s = optimal_half_width(generous, SIGMA, GAS_OVER_VALUE, tick_spacing=60)
    assert s.optimal_half_width < tick_spacing_half_width(60)
    assert s.realisable_half_width == pytest.approx(tick_spacing_half_width(60))
    assert s.binding_constraint == "tick_grid"


def test_tick_grid_widens_with_the_fee_tier():
    """Uniswap bundles spacing with the tier, so the floor differs per pool."""
    a, b, c = (tick_spacing_half_width(s) for s in (10, 60, 200))
    assert a < b < c
    assert c / a > 15


def test_fee_saturation_is_bounded_by_the_whole_pool():
    """A position cannot earn more than the pool's entire fee revenue."""
    revenue_over_value, beta = 5.0, 3e-4
    for delta in (1e-6, 1e-5, 1e-4):
        assert fee_rate_saturating(delta, revenue_over_value, beta) <= revenue_over_value


def test_saturating_and_linear_models_agree_when_the_position_is_small():
    revenue_over_value, beta = 5.0, 3e-4
    delta = 0.10                                   # delta >> beta
    linear = fee_rate(delta, revenue_over_value * beta)
    assert fee_rate_saturating(delta, revenue_over_value, beta) == pytest.approx(linear, rel=0.01)


def test_capacity_floor_is_far_below_the_tick_floor_for_a_retail_position():
    """Open question 4: which floor binds is a question about position size.

    A $100k position on a pool with ~$35m of active liquidity saturates at
    ~3bp, twenty times below the 60-tick grid — so the grid binds and capacity
    does not until the position is roughly $2m.
    """
    # Measured: a $100k position held 0.28959% of active liquidity at +/-10%.
    beta = saturation_half_width(0.1020, 0.0028959)
    assert beta == pytest.approx(2.95e-4, rel=0.02)
    assert beta < tick_spacing_half_width(60) / 10

    cap = capacity_limit_usd(100_000, 0.1020, 0.0028959, tick_spacing=60)
    assert 1.5e6 < cap < 2.5e6, f"capacity limit came out at ${cap:,.0f}"


def test_half_width_from_prices_measures_about_the_geometric_centre():
    d = half_width_from_prices(1074.98, 1318.23)
    assert d == pytest.approx(math.log(1318.23 / math.sqrt(1074.98 * 1318.23)))
    assert 0.10 < d < 0.11


def test_degenerate_inputs_are_rejected():
    with pytest.raises(ValueError):
        half_width_from_prices(100.0, 100.0)
    with pytest.raises(ValueError):
        fee_rate(0.0, F_PROFITABLE)
    with pytest.raises(ValueError):
        optimal_half_width(F_PROFITABLE, 0.0, GAS_OVER_VALUE)
