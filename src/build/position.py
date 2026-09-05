"""Simulated Uniswap v3 LP position — sizing, value, delta, range state.

Reconstructs what a position *would* have earned. It is a simulation, not an
observation of a real position, and the path-dependence of v3 range management
is approximated — stated in the limitations, not buried.

All position maths goes through `src.utils.precision`; nothing is recomputed
inline. Amounts are exact integers in token base units; only the final USD
valuation becomes a Decimal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pandas as pd

from src.utils import precision as pr
from src.utils.config import PoolSpec

#: Position notional is sized against a reference L before scaling. Any value
#: works; this one keeps the intermediate amounts comfortably large.
_REFERENCE_LIQUIDITY = 10**18


class RangeState(str, Enum):
    """Where the pool's tick sits relative to the position's range.

    Named in **tick space**, deliberately, because tick space is what drives
    fee accrual and it is unambiguous. Price space is not: for an inverted pool
    (token0 the stable, token1 the risky asset) the raw price is
    risky-per-stable, so the tick *falls* as the risky asset appreciates. A
    position on ETH/USDC whose tick drops below `tick_lower` has had ETH move
    *above* the top of its USD range.

    Use :func:`price_side` for anything a human reads.
    """

    TICK_BELOW = "tick_below"      # position is entirely token0
    IN_RANGE = "in_range"
    TICK_ABOVE = "tick_above"      # position is entirely token1


def price_side(state: "RangeState", spec: PoolSpec) -> str:
    """Translate a tick-space range state into price-space words.

    Exists because "below" meaning "the risky asset rallied" is a trap that
    will eventually be read the wrong way round in a table or a chart caption.
    """
    if state is RangeState.IN_RANGE:
        return "in_range"
    high = (state is RangeState.TICK_BELOW) if spec.invert_price else (state is RangeState.TICK_ABOVE)
    return "price_above_range" if high else "price_below_range"


class RecentreRule(str, Enum):
    NEVER = "never"
    ON_RANGE_EXIT = "on_range_exit"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class Position:
    """A concrete position. Every field is fixed at open time."""

    pool_id: str
    entry_block: int
    entry_sqrt_price_x96: int
    tick_lower: int
    tick_upper: int
    liquidity: int                 # exact, uint128 scale
    notional_usd: Decimal

    @property
    def sqrt_lower_x96(self) -> int:
        return pr.get_sqrt_ratio_at_tick(self.tick_lower)

    @property
    def sqrt_upper_x96(self) -> int:
        return pr.get_sqrt_ratio_at_tick(self.tick_upper)


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #

def token_usd_prices(spec: PoolSpec, pool_price: Decimal) -> tuple[Decimal, Decimal]:
    """USD price of each token, given the pool's human-readable price.

    `pool_price` is what `pool_state` produces: for an inverted pool (token0 the
    stable, token1 the risky asset) it is stable-per-risky, so token0 is worth
    $1 and token1 is worth `pool_price`.

    A stable/stable pool prices both legs at ~$1, using the pool's own quote for
    token1 so any depeg is carried rather than assumed away. A pool with no
    stable leg (WBTC/ETH) needs an external USD reference and is not handled
    here — raising is better than silently inventing a numeraire.
    """
    stables = {"USDC", "USDT", "DAI"}
    t0, t1 = spec.token0.symbol, spec.token1.symbol
    if t0 in stables and t1 in stables:
        return Decimal(1), Decimal(str(pool_price))
    if spec.invert_price:                      # token0 stable, token1 risky
        return Decimal(1), Decimal(str(pool_price))
    if t1 in stables:                          # token1 stable, token0 risky
        return Decimal(str(pool_price)), Decimal(1)
    raise NotImplementedError(
        f"{spec.id} has no stable leg; USD valuation needs an external price "
        f"reference for {t0}/{t1}. Add one explicitly rather than assuming one."
    )


def amounts_at(position: Position, sqrt_price_x96: int) -> tuple[int, int]:
    """Token amounts held at a given price, in base units."""
    return pr.position_amounts(
        sqrt_price_x96, position.sqrt_lower_x96, position.sqrt_upper_x96, position.liquidity
    )


def value_usd(position: Position, sqrt_price_x96: int, pool_price: Decimal, spec: PoolSpec) -> Decimal:
    """Mark-to-market USD value of both legs at the pool price."""
    a0, a1 = amounts_at(position, sqrt_price_x96)
    p0, p1 = token_usd_prices(spec, pool_price)
    return (
        Decimal(a0) / Decimal(10**spec.token0.decimals) * p0
        + Decimal(a1) / Decimal(10**spec.token1.decimals) * p1
    )


def risky_delta(position: Position, sqrt_price_x96: int, spec: PoolSpec) -> Decimal:
    """Holding of the risky asset, in its own units. This is the hedge ratio.

    Emphatically not 0.5 of the notional: a v3 position sweeps from fully-risky
    at the bottom of its range to fully-cash at the top, and that path
    dependence is open question 7.
    """
    a0, a1 = amounts_at(position, sqrt_price_x96)
    if spec.invert_price:                      # token1 is the risky asset
        return Decimal(a1) / Decimal(10**spec.token1.decimals)
    return Decimal(a0) / Decimal(10**spec.token0.decimals)


def range_state(position: Position, tick: int) -> RangeState:
    """Where the pool price sits relative to the range.

    Boundary convention follows the pool: a position is active for
    `tick_lower <= tick < tick_upper`. An off-by-one here accrues fees while
    out of range and overstates returns.
    """
    if tick < position.tick_lower:
        return RangeState.TICK_BELOW
    if tick >= position.tick_upper:
        return RangeState.TICK_ABOVE
    return RangeState.IN_RANGE


# --------------------------------------------------------------------------- #
# Opening a position
# --------------------------------------------------------------------------- #

def snap_range(
    pool_price: Decimal, half_width: Decimal, spec: PoolSpec
) -> tuple[int, int]:
    """Range bounds as ticks, snapped outward to the pool's tick spacing.

    Snapping outward guarantees the realised range is never narrower than
    requested, so a `+/-10%` position is at least +/-10% wide. Inward snapping
    would quietly bias every position toward more concentration than specified.
    """
    lo_price = Decimal(str(pool_price)) * (Decimal(1) - Decimal(str(half_width)))
    hi_price = Decimal(str(pool_price)) * (Decimal(1) + Decimal(str(half_width)))

    d0, d1, inv = spec.token0.decimals, spec.token1.decimals, spec.invert_price
    t_a = pr.price_to_tick(lo_price, d0, d1, inv)
    t_b = pr.price_to_tick(hi_price, d0, d1, inv)
    # Inverting reverses the direction of price in tick space.
    t_lo, t_hi = (t_a, t_b) if t_a <= t_b else (t_b, t_a)

    s = spec.tick_spacing
    t_lo = int(math.floor(t_lo / s) * s)
    t_hi = int(math.ceil(t_hi / s) * s)
    if t_hi <= t_lo:
        t_hi = t_lo + s
    return t_lo, t_hi


def open_position(
    spec: PoolSpec, block: int, sqrt_price_x96: int, pool_price: Decimal,
    notional_usd: Decimal, half_width: Decimal,
) -> Position:
    """Size a position to a USD notional at the prevailing price.

    Liquidity scales linearly in the token amounts, so the size is found by
    valuing a reference liquidity and scaling — exactly, in Decimal, with the
    result floored to an integer as the pool would hold it.
    """
    t_lo, t_hi = snap_range(pool_price, half_width, spec)
    probe = Position(spec.id, block, sqrt_price_x96, t_lo, t_hi, _REFERENCE_LIQUIDITY, Decimal(0))
    probe_value = value_usd(probe, sqrt_price_x96, pool_price, spec)
    if probe_value <= 0:
        raise ValueError(
            f"reference position has non-positive value at block {block}; "
            f"range [{t_lo}, {t_hi}] may not bracket the price"
        )
    liquidity = int(Decimal(_REFERENCE_LIQUIDITY) * Decimal(str(notional_usd)) / probe_value)
    return Position(spec.id, block, sqrt_price_x96, t_lo, t_hi, liquidity, Decimal(str(notional_usd)))


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #

def simulate(pool_state: pd.DataFrame, position: Position, spec: PoolSpec) -> pd.DataFrame:
    """Block-by-block value, delta and range state over the sample."""
    rows = []
    for blk, ts, sqrt_x96, tick, price in zip(
        pool_state["block_number"], pool_state["block_timestamp"],
        pool_state["sqrt_price_x96"], pool_state["tick"], pool_state["price"],
    ):
        s = int(sqrt_x96)
        a0, a1 = amounts_at(position, s)
        rows.append(
            {
                "block_number": int(blk),
                "block_timestamp": int(ts),
                "sqrt_price_x96": s,
                "tick": int(tick),
                "price": Decimal(str(price)),
                "amount0": a0,
                "amount1": a1,
                "value_usd": value_usd(position, s, Decimal(str(price)), spec),
                "risky_delta": risky_delta(position, s, spec),
                "range_state": range_state(position, int(tick)).value,
                "price_side": price_side(range_state(position, int(tick)), spec),
            }
        )
    out = pd.DataFrame(rows)
    out["in_range"] = out["range_state"] == RangeState.IN_RANGE.value
    return out
