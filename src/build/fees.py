"""Fee accrual for a simulated position.

    fee_earned = swap_volume * fee_tier * (L_position / L_active_at_tick)

Fees accrue **only while the position is in range**. Accruing while out of
range is the single most common way to overstate LP returns, and shows up in
the Stage 2 gate as fees far above the subgraph.

Two approaches to `L_active_at_tick`, per Stage 2.2:

    A — event replay: rebuild the full tick liquidity map from every Mint and
        Burn since pool creation. Exact, expensive.
    B — pool state:   use the `liquidity` field carried on each Swap event.
        Cheap, and sufficient while the position is small relative to the pool.

Start with B. Validate against A on one week; keep B if they agree within 1%.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.utils.config import PoolSpec


def accrue_fees_approach_b(
    position, pool_state: pd.DataFrame, spec: PoolSpec
) -> pd.Series:
    """Fee accrual using the `liquidity` field on each Swap event.

    Valid while the position does not meaningfully move the denominator. A
    $100k position in a $200m pool shifts `L_active` by ~0.05%.
    """
    raise NotImplementedError("Stage 2.2")


def build_tick_liquidity_map(mints: pd.DataFrame, burns: pd.DataFrame) -> pd.DataFrame:
    """Approach A: net liquidity delta per tick, replayed from pool creation.

    Mints add `L` at `tick_lower` and subtract at `tick_upper`; burns reverse
    it. Active liquidity at any tick is the running sum of deltas up to it.
    """
    raise NotImplementedError("Stage 2.2")


def accrue_fees_approach_a(
    position, pool_state: pd.DataFrame, tick_map: pd.DataFrame, spec: PoolSpec
) -> pd.Series:
    """Exact fee accrual from the replayed tick liquidity map."""
    raise NotImplementedError("Stage 2.2")


def validate_b_against_a(
    position, pool_state: pd.DataFrame, mints: pd.DataFrame, burns: pd.DataFrame,
    spec: PoolSpec, tolerance: Decimal = Decimal("0.01"),
) -> dict:
    """Run both approaches over one week and report the gap.

    Agreement within `tolerance` keeps B and the choice is documented. Wider
    agreement than that means B is not safe at this position size.
    """
    raise NotImplementedError("Stage 2.2")


def capacity_limit(
    pool_state: pd.DataFrame, spec: PoolSpec, sizes: list[Decimal]
) -> pd.DataFrame:
    """Open question 4: the size at which approach B breaks down.

    Sweeps notional and reports the A-vs-B divergence at each. The answer is
    the capacity limit of any strategy built on this pipeline, so it is a
    number the paper owes the reader, not a caveat.
    """
    raise NotImplementedError("Stage 2.2 — open question 4")


def gate_fee_accrual_vs_subgraph(
    simulated: pd.Series, subgraph_fees: pd.Series, tolerance: Decimal = Decimal("0.02")
) -> dict:
    """Stage 2 GATE: simulated fees within 2% of the subgraph-derived figure.

    Failure means stop and diagnose. Fees above the subgraph almost always mean
    accrual while out of range.
    """
    raise NotImplementedError("Stage 2.3 — GATE")
