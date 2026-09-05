"""Simulated Uniswap v3 LP position — value, range state, re-centring.

Reconstructs what a position *would* have earned. It is a simulation, not an
observation of a real position, and the path-dependence of v3 range management
is approximated — stated in the limitations, not buried.

Position maths (all via `src.utils.precision`, never inline):

    In range:  amount0 = L * (1/sqrt(P) - 1/sqrt(P_upper))
               amount1 = L * (sqrt(P) - sqrt(P_lower))
    Below range: entirely token0
    Above range: entirely token1
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pandas as pd

from src.utils.config import PoolSpec


class RecentreRule(str, Enum):
    NEVER = "never"
    ON_RANGE_EXIT = "on_range_exit"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class PositionSpec:
    """A position is not well defined until all of these are fixed."""

    notional_usd: Decimal
    range_half_width: Decimal          # 0.10 -> +/-10%
    recentre_rule: RecentreRule
    entry_block: int
    tick_lower: int
    tick_upper: int


def open_position(
    spec: PoolSpec, entry_state, notional_usd: Decimal, half_width: Decimal
) -> PositionSpec:
    """Size a position at entry, snapping the range to the pool's tick spacing.

    Range bounds must be multiples of `tick_spacing`; the requested +/-10% is
    snapped outward so the realised range is never narrower than specified.
    """
    raise NotImplementedError("Stage 2.1")


def position_value(position: PositionSpec, state, spec: PoolSpec) -> Decimal:
    """Mark-to-market value of both legs at the pool price."""
    raise NotImplementedError("Stage 2.1")


def position_delta(position: PositionSpec, state, spec: PoolSpec) -> Decimal:
    """Instantaneous delta — the token0 holding, in units of the risky asset.

    This is the hedge ratio. It is emphatically not 0.5: a v3 position's delta
    moves from fully-risky to fully-cash as price traverses the range, and that
    path dependence is open question 7.
    """
    raise NotImplementedError("Stage 2.1 / 0.1")


def range_state(position: PositionSpec, state) -> str:
    """`'in_range'`, `'below'` or `'above'`.

    Transitions must occur exactly at the tick boundary — an off-by-one here
    accrues fees while out of range and overstates returns.
    """
    raise NotImplementedError("Stage 2.1")


def simulate(
    pool_state: pd.DataFrame, spec: PoolSpec, position_config: dict
) -> pd.DataFrame:
    """Block-by-block simulation over the sample: value, delta, range state, events.

    Emits a `events` column marking mints, burns and re-centrings, which
    `gas.py` prices at the actual gas of those blocks.
    """
    raise NotImplementedError("Stage 2.1")


def build_cohorts(pool_state: pd.DataFrame, spec: PoolSpec, config: dict) -> pd.DataFrame:
    """Monthly entry cohorts, per Stage 0.2.

    Independent entry points rather than one path, so the headline number is
    not an artefact of a single entry date.
    """
    raise NotImplementedError("Stage 2.1")
