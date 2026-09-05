"""Position reconstruction and fee accrual.

The traps these cover are orientation traps: for an inverted pool the tick runs
*opposite* to the USD price, so range bounds, delta and range state can all be
individually plausible and jointly backwards.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from src.build.fees import _boundary_fraction, _sub256, accrue_fees_approach_b
from src.build.position import (Position, RangeState, amounts_at, open_position,
                                price_side, range_state, risky_delta, snap_range,
                                token_usd_prices, value_usd)
from src.utils import precision as pr
from src.utils.config import pool

SPEC = pool("ETH_USDC_30bp")          # token0=USDC(6), token1=WETH(18), inverted
ENTRY_PRICE = Decimal("1196.14")


def _sqrt_at(price: Decimal) -> int:
    return pr.price_to_sqrt_price_x96(price, 6, 18, invert=True)


def _position(half_width="0.10") -> Position:
    s = _sqrt_at(ENTRY_PRICE)
    return open_position(SPEC, 1, s, ENTRY_PRICE, Decimal("100000"), Decimal(half_width))


# --------------------------------------------------------------------------- #
# Range construction
# --------------------------------------------------------------------------- #

def test_range_brackets_the_entry_price_and_never_narrower_than_asked():
    lo_t, hi_t = snap_range(ENTRY_PRICE, Decimal("0.10"), SPEC)
    assert lo_t % SPEC.tick_spacing == 0 and hi_t % SPEC.tick_spacing == 0
    # inverted: the LOW tick is the HIGH USD price
    p_at_hi_tick = pr.tick_to_price(hi_t, 6, 18, True)
    p_at_lo_tick = pr.tick_to_price(lo_t, 6, 18, True)
    lo_usd, hi_usd = sorted([p_at_hi_tick, p_at_lo_tick])
    assert lo_usd < ENTRY_PRICE < hi_usd
    assert lo_usd <= ENTRY_PRICE * Decimal("0.90"), "snapped inward — range too narrow"
    assert hi_usd >= ENTRY_PRICE * Decimal("1.10"), "snapped inward — range too narrow"


def test_position_is_sized_to_the_notional():
    pos = _position()
    v = value_usd(pos, _sqrt_at(ENTRY_PRICE), ENTRY_PRICE, SPEC)
    assert abs(v - Decimal("100000")) / Decimal("100000") < Decimal("1e-6")


def test_narrower_range_concentrates_more_liquidity_per_dollar():
    wide, narrow = _position("0.50"), _position("0.02")
    assert narrow.liquidity > wide.liquidity * 5


# --------------------------------------------------------------------------- #
# Orientation — the trap
# --------------------------------------------------------------------------- #

def test_tick_falls_as_the_risky_asset_appreciates():
    """On an inverted pool a rising USD price means a FALLING tick."""
    lo = pr.price_to_tick(Decimal("1200"), 6, 18, invert=True)
    hi = pr.price_to_tick(Decimal("1600"), 6, 18, invert=True)
    assert hi < lo


def test_price_side_translates_tick_space_to_price_space():
    """`TICK_BELOW` on an inverted pool means the price is ABOVE the range."""
    assert price_side(RangeState.TICK_BELOW, SPEC) == "price_above_range"
    assert price_side(RangeState.TICK_ABOVE, SPEC) == "price_below_range"
    assert price_side(RangeState.IN_RANGE, SPEC) == "in_range"


def test_delta_goes_to_zero_when_the_risky_asset_rallies_out_of_range():
    """ETH above the range -> position fully converted to USDC -> delta 0."""
    pos = _position()
    high = _sqrt_at(ENTRY_PRICE * Decimal("2"))
    assert range_state(pos, pr.get_tick_at_sqrt_ratio(high)) is RangeState.TICK_BELOW
    assert risky_delta(pos, high, SPEC) == 0


def test_delta_is_maximal_when_the_risky_asset_collapses_below_range():
    pos = _position()
    low = _sqrt_at(ENTRY_PRICE / Decimal("2"))
    a0, a1 = amounts_at(pos, low)
    assert a0 == 0 and a1 > 0, "below the USD range the position is all WETH"
    assert risky_delta(pos, low, SPEC) > 0


def test_delta_is_not_half_the_notional():
    """A v3 delta comes from the position formula, never from a 0.5 assumption."""
    pos = _position()
    d = risky_delta(pos, _sqrt_at(ENTRY_PRICE), SPEC)
    share = d * ENTRY_PRICE / Decimal("100000")
    assert Decimal("0.3") < share < Decimal("0.7")
    assert share != Decimal("0.5")


def test_usd_prices_require_a_stable_leg():
    wbtc_eth = pool("WBTC_ETH_30bp")
    with pytest.raises(NotImplementedError, match="no stable leg"):
        token_usd_prices(wbtc_eth, Decimal("15"))


# --------------------------------------------------------------------------- #
# Fee accrual
# --------------------------------------------------------------------------- #

def test_uint256_subtraction_wraps():
    """feeGrowthInside is allowed to underflow; the difference is still correct."""
    assert _sub256(5, 7) == (1 << 256) - 2
    assert _sub256(_sub256(5, 7) + 7, 5) == 0


def test_boundary_fraction_credits_only_the_inside_portion():
    pos = Position("p", 1, 1, tick_lower=1000, tick_upper=2000, liquidity=10**18,
                   notional_usd=Decimal(0))
    assert _boundary_fraction(1200, 1400, pos) == 1                    # wholly inside
    assert _boundary_fraction(2500, 3000, pos) == 0                    # wholly outside
    assert _boundary_fraction(1800, 2200, pos) == Decimal(200) / Decimal(400)  # half out
    assert _boundary_fraction(900, 1100, pos) == Decimal(100) / Decimal(200)   # half in


def test_boundary_fraction_handles_a_stationary_tick():
    pos = Position("p", 1, 1, 1000, 2000, 10**18, Decimal(0))
    assert _boundary_fraction(1500, 1500, pos) == 1
    assert _boundary_fraction(2500, 2500, pos) == 0


def test_no_fees_accrue_out_of_range():
    pos = _position()
    out_tick = pos.tick_lower - 5000          # price far above the USD range
    swaps = pd.DataFrame({
        "block_number": [10, 11], "block_timestamp": [100, 112],
        "tick": [out_tick, out_tick], "liquidity": [10**20, 10**20],
        "amount0": [10**9, 0], "amount1": [0, 10**18],
    })
    acc = accrue_fees_approach_b(swaps, pos, SPEC, entry_tick=out_tick)
    assert acc.fee0.sum() == 0 and acc.fee1.sum() == 0


def test_fee_is_charged_on_the_input_token_only():
    pos = _position()
    mid = (pos.tick_lower + pos.tick_upper) // 2
    swaps = pd.DataFrame({
        "block_number": [10], "block_timestamp": [100], "tick": [mid],
        "liquidity": [pos.liquidity], "amount0": [10**9], "amount1": [-(10**17)],
    })
    acc = accrue_fees_approach_b(swaps, pos, SPEC, entry_tick=mid)
    assert acc.fee0.iloc[0] > 0, "token0 came in, so token0 fee is charged"
    assert acc.fee1.iloc[0] == 0, "token1 went out; no fee on the output leg"
    # position holds all the active liquidity -> it earns the whole fee
    assert acc.fee0.iloc[0] == pytest.approx(10**9 * 0.003, rel=1e-6)


def test_fee_scales_with_liquidity_share():
    pos = _position()
    mid = (pos.tick_lower + pos.tick_upper) // 2
    base = dict(block_number=[10], block_timestamp=[100], tick=[mid],
                amount0=[10**9], amount1=[0])
    full = accrue_fees_approach_b(pd.DataFrame({**base, "liquidity": [pos.liquidity]}),
                                  pos, SPEC, entry_tick=mid).fee0.iloc[0]
    tenth = accrue_fees_approach_b(pd.DataFrame({**base, "liquidity": [pos.liquidity * 10]}),
                                   pos, SPEC, entry_tick=mid).fee0.iloc[0]
    assert tenth == pytest.approx(full / 10, rel=1e-6)
