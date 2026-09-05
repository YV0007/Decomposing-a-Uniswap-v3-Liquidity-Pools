"""Tests for exact Uniswap v3 arithmetic.

These are the only tests in the suite that guard a *silent* failure mode: a
float64 in the price path, a transposed decimal, or a mistyped TickMath
constant produces plausible numbers that are wrong. Everything downstream
inherits the error.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.utils import precision as pr

# ETH/USDC pools: token0 = USDC (6), token1 = WETH (18), price inverted.
USDC_DEC, WETH_DEC = 6, 18

TICK_SAMPLES = [
    pr.MIN_TICK, -887000, -500000, -100000, -50000, -10000, -887, -60, -1,
    0, 1, 60, 887, 10000, 50000, 100000, 500000, 887000, pr.MAX_TICK,
]


# --------------------------------------------------------------------------- #
# Float rejection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [1.0, 0.1, float("nan"), True])
def test_float_and_bool_are_rejected(bad):
    with pytest.raises(pr.PrecisionError):
        pr.reject_float(bad, "bad")


def test_sqrt_price_rejects_float():
    with pytest.raises(pr.PrecisionError):
        pr.raw_price_from_sqrt_price_x96(1.5e30)


def test_tick_rejects_float():
    with pytest.raises(pr.PrecisionError):
        pr.tick_to_raw_price(100.0)


# --------------------------------------------------------------------------- #
# TickMath cross-check: integer path vs independent Decimal path
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tick", TICK_SAMPLES)
def test_tickmath_matches_decimal(tick):
    """The canonical integer TickMath and `1.0001 ** tick` must agree.

    They are independent implementations, so agreement here rules out a
    mistyped magic constant. The tolerance is the reference implementation's
    own quantisation, not slack for our sloppiness: it rounds up at the
    Q128 -> Q96 step (at most one unit of sqrtPriceX96, which dominates at
    extreme negative ticks where the ratio is only ~4.3e9) and truncates
    through the >>128 multiply chain (relative, dominating at high ticks,
    observed at most 3e-20).
    """
    from_int = Decimal(pr.get_sqrt_ratio_at_tick(tick))
    from_dec = pr.tick_to_raw_price(tick).sqrt() * Decimal(pr.Q96)
    abs_gap = abs(from_int - from_dec)
    rel = abs_gap / from_dec
    assert abs_gap <= Decimal(1) or rel < Decimal("1e-18"), (
        f"tick {tick}: abs gap {abs_gap}, relative {rel} — suspect a mistyped "
        f"TickMath constant"
    )


def test_tickmath_is_monotone():
    ticks = list(range(-1000, 1000, 7))
    ratios = [pr.get_sqrt_ratio_at_tick(t) for t in ticks]
    assert ratios == sorted(ratios)
    assert len(set(ratios)) == len(ratios)


# --------------------------------------------------------------------------- #
# Round trips — must be exact
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tick", TICK_SAMPLES)
@pytest.mark.parametrize("invert", [False, True])
def test_tick_price_tick_roundtrip_is_exact(tick, invert):
    price = pr.tick_to_price(tick, USDC_DEC, WETH_DEC, invert=invert)
    assert pr.price_to_tick(price, USDC_DEC, WETH_DEC, invert=invert) == tick


@pytest.mark.parametrize("tick", [t for t in TICK_SAMPLES if -800000 < t < 800000])
def test_sqrt_ratio_tick_roundtrip_is_exact(tick):
    sqrt_ratio = pr.get_sqrt_ratio_at_tick(tick)
    assert pr.get_tick_at_sqrt_ratio(sqrt_ratio) == tick


@pytest.mark.parametrize("human", [Decimal("1200"), Decimal("2345.67"), Decimal("4999.999")])
def test_human_price_roundtrip(human):
    raw = pr.to_raw_price(human, USDC_DEC, WETH_DEC, invert=True)
    back = pr.to_human_price(raw, USDC_DEC, WETH_DEC, invert=True)
    assert abs(back - human) / human < Decimal("1e-40")


# --------------------------------------------------------------------------- #
# Decimals and inversion — the "price off by 10**12" and "price inverted" traps
# --------------------------------------------------------------------------- #

def test_eth_usdc_price_is_in_a_plausible_range():
    """A real-ish sqrtPriceX96 must decode to a sane USD-per-ETH number.

    Catches both the missing decimal adjustment (off by 10**12) and the missing
    inversion (reciprocal), because either lands far outside these bounds.
    """
    tick = pr.price_to_tick(Decimal("2000"), USDC_DEC, WETH_DEC, invert=True)
    sqrt_x96 = pr.get_sqrt_ratio_at_tick(tick)
    price = pr.sqrt_price_x96_to_price(sqrt_x96, USDC_DEC, WETH_DEC, invert=True)
    assert Decimal("1999") < price < Decimal("2001")


def test_forgetting_to_invert_is_detectable():
    tick = pr.price_to_tick(Decimal("2000"), USDC_DEC, WETH_DEC, invert=True)
    sqrt_x96 = pr.get_sqrt_ratio_at_tick(tick)
    wrong = pr.sqrt_price_x96_to_price(sqrt_x96, USDC_DEC, WETH_DEC, invert=False)
    assert wrong < Decimal("0.001")


def test_forgetting_decimals_is_detectable():
    tick = pr.price_to_tick(Decimal("2000"), USDC_DEC, WETH_DEC, invert=True)
    sqrt_x96 = pr.get_sqrt_ratio_at_tick(tick)
    wrong = pr.sqrt_price_x96_to_price(sqrt_x96, 0, 0, invert=True)
    # Dropping the 6-vs-18 adjustment scales the inverted price down by 10**12.
    assert wrong / Decimal("2000") < Decimal("1e-10")


# --------------------------------------------------------------------------- #
# Liquidity <-> amounts
# --------------------------------------------------------------------------- #

def test_position_is_single_sided_outside_range():
    lo = pr.get_sqrt_ratio_at_tick(-1000)
    hi = pr.get_sqrt_ratio_at_tick(1000)
    L = 10**18

    a0, a1 = pr.position_amounts(pr.get_sqrt_ratio_at_tick(-2000), lo, hi, L)
    assert a0 > 0 and a1 == 0, "below range the position is all token0"

    a0, a1 = pr.position_amounts(pr.get_sqrt_ratio_at_tick(2000), lo, hi, L)
    assert a0 == 0 and a1 > 0, "above range the position is all token1"

    a0, a1 = pr.position_amounts(pr.get_sqrt_ratio_at_tick(0), lo, hi, L)
    assert a0 > 0 and a1 > 0, "in range the position holds both"


def test_amounts_are_symmetric_at_range_centre():
    """At the geometric centre of a range the two legs have equal value."""
    lo_t, hi_t = -1000, 1000
    lo, hi = pr.get_sqrt_ratio_at_tick(lo_t), pr.get_sqrt_ratio_at_tick(hi_t)
    mid = pr.get_sqrt_ratio_at_tick(0)
    L = 10**24
    a0, a1 = pr.position_amounts(mid, lo, hi, L)
    price_raw = pr.raw_price_from_sqrt_price_x96(mid)
    value_of_a0_in_token1 = Decimal(a0) * price_raw
    rel = abs(value_of_a0_in_token1 - Decimal(a1)) / Decimal(a1)
    assert rel < Decimal("1e-6"), f"legs unbalanced at centre: {rel}"


def test_amount_order_does_not_matter():
    lo, hi = pr.get_sqrt_ratio_at_tick(-500), pr.get_sqrt_ratio_at_tick(500)
    L = 10**20
    assert pr.amount0_for_liquidity(lo, hi, L) == pr.amount0_for_liquidity(hi, lo, L)
    assert pr.amount1_for_liquidity(lo, hi, L) == pr.amount1_for_liquidity(hi, lo, L)
