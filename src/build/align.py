"""Aligning continuous CEX prices to discrete ~12s Ethereum blocks.

This is a modelling choice, not a mechanical step, and it is open question 3.
The rule chosen determines what "the pool was stale by X" means, and therefore
determines LVR. It is isolated here so alternatives can be swept without
touching the LVR computation.

**Baseline: the last CEX trade at or before the block timestamp.**

The boundary subtlety that makes this non-obvious
-------------------------------------------------
The reference series is 1-second klines. The kline for second ``s`` covers
``[s, s+1)`` and its ``close`` is the last trade in that window — which may be
timestamped *after* ``s``. So for a block at timestamp ``T``, matching the kline
for second ``T`` admits up to one second of lookahead: the close could be a
trade at ``T + 0.9``, information that did not exist when the block was built.

The correct match is the latest kline with ``s <= T - 1``, whose close is
strictly before ``T``. One second of extra staleness is the price of being
strictly causal, and staleness that is known and bounded is much safer than
lookahead that is small and invisible.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

import pandas as pd

#: Beacon chain genesis. Every post-Merge block timestamp is genesis + 12*slot.
MERGE_GENESIS_TS = 1606824023
SLOT_SECONDS = 12


class AlignmentRule(str, Enum):
    """The alternatives swept for open question 3."""

    #: Baseline. Latest kline closing strictly at or before the block timestamp.
    LAST_TRADE_AT_OR_BEFORE_BLOCK_TS = "last_trade_at_or_before_block_ts"
    #: One beacon slot earlier. Tests sensitivity to proposer-set timestamps,
    #: which can drift by seconds. Named for what it does: the true parent block
    #: is one slot earlier only when no slot was missed, and we do not fetch the
    #: parent to find out.
    ONE_SLOT_EARLIER = "one_slot_earlier"
    #: Interpolates across the block boundary. **Uses lookahead by
    #: construction** and exists only to quantify how much the answer moves.
    #: Excluded from every headline number and flagged in its own output.
    MIDPOINT_INTERPOLATION = "midpoint_interpolation"


LOOKAHEAD_RULES = {AlignmentRule.MIDPOINT_INTERPOLATION}


def _key_second(block_ts: pd.Series, rule: AlignmentRule) -> pd.Series:
    """The latest kline-open second whose close is admissible under `rule`."""
    if rule is AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS:
        return block_ts - 1
    if rule is AlignmentRule.ONE_SLOT_EARLIER:
        return block_ts - SLOT_SECONDS - 1
    if rule is AlignmentRule.MIDPOINT_INTERPOLATION:
        return block_ts + SLOT_SECONDS // 2      # deliberately forward-looking
    raise ValueError(f"unknown rule {rule}")


def align_cex_to_blocks(
    blocks: pd.DataFrame,
    cex: pd.DataFrame,
    rule: AlignmentRule = AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS,
    block_ts_col: str = "block_timestamp",
) -> pd.DataFrame:
    """Attach a CEX reference price to every block.

    Parameters
    ----------
    blocks
        Must carry `block_ts_col` as integer unix seconds.
    cex
        `[second, close]` from `binance_data.load_klines_1s`, sorted ascending.
    rule
        See :class:`AlignmentRule`. The default is the only one used in headline
        numbers.

    Returns the input with `cex_price` (Decimal), `cex_second`,
    `staleness_seconds` (how old the reference is relative to the block) and
    `uses_lookahead` attached. Rows with no admissible reference — the first
    block of the sample, or a gap in the kline series — get a null price rather
    than a forward fill from the future.
    """
    if not cex["second"].is_monotonic_increasing:
        cex = cex.sort_values("second")

    left = blocks.copy()
    left["_key"] = _key_second(left[block_ts_col].astype("int64"), rule)
    left = left.sort_values("_key")

    merged = pd.merge_asof(
        left,
        cex[["second", "close"]].rename(columns={"second": "cex_second"}),
        left_on="_key",
        right_on="cex_second",
        direction="backward",       # last observation at or before the key
    )

    merged["cex_price"] = [
        Decimal(str(v)) if pd.notna(v) else None for v in merged["close"]
    ]
    merged["staleness_seconds"] = merged[block_ts_col] - merged["cex_second"]
    merged["uses_lookahead"] = rule in LOOKAHEAD_RULES
    merged = merged.drop(columns=["_key", "close"])
    return merged.sort_values(block_ts_col).reset_index(drop=True)


def assert_causal(aligned: pd.DataFrame, block_ts_col: str = "block_timestamp") -> None:
    """Raise if any matched reference could contain post-block information.

    A kline opening at second `s` closes strictly before `s + 1`, so causality
    requires ``cex_second + 1 <= block_timestamp``. Checked directly rather than
    trusted to the merge direction.
    """
    if bool(aligned["uses_lookahead"].any()):
        raise AssertionError(
            "aligned frame was built with a lookahead rule; it must not reach a "
            "headline number"
        )
    have = aligned["cex_second"].notna()
    bad = aligned.loc[have, "cex_second"] + 1 > aligned.loc[have, block_ts_col]
    if bool(bad.any()):
        n = int(bad.sum())
        raise AssertionError(
            f"{n} rows use a CEX observation that can postdate the block. The "
            f"kline for second s closes in [s, s+1), so s + 1 <= block_timestamp "
            f"is required."
        )


def price_gap(aligned: pd.DataFrame, pool_price_col: str = "price") -> pd.Series:
    """Relative gap ``(cex - pool) / pool``. The raw material of empirical LVR.

    Positive means the CEX is above the pool, so the pool is selling the risky
    asset too cheaply and an arbitrageur buys from it.
    """
    out = []
    for pool_p, cex_p in zip(aligned[pool_price_col], aligned["cex_price"]):
        if cex_p is None or pool_p is None:
            out.append(None)
        else:
            out.append((Decimal(str(cex_p)) - Decimal(str(pool_p))) / Decimal(str(pool_p)))
    return pd.Series(out, index=aligned.index)


def alignment_sensitivity(blocks: pd.DataFrame, cex: pd.DataFrame) -> pd.DataFrame:
    """Open question 3: run every rule and report how far the answer moves.

    If the gap distribution barely moves, the rule earns a sentence. If it
    moves materially, it earns a robustness slide. Either way the number is
    reported rather than assumed.
    """
    rows = []
    for rule in AlignmentRule:
        aligned = align_cex_to_blocks(blocks, cex, rule)
        gap = price_gap(aligned).dropna()
        gaps = [float(g) for g in gap]
        s = pd.Series(gaps)
        rows.append(
            {
                "rule": rule.value,
                "uses_lookahead": rule in LOOKAHEAD_RULES,
                "n": len(s),
                "mean_gap_bps": s.mean() * 1e4,
                "mean_abs_gap_bps": s.abs().mean() * 1e4,
                "p95_abs_gap_bps": s.abs().quantile(0.95) * 1e4,
                "median_staleness_s": float(aligned["staleness_seconds"].median()),
            }
        )
    return pd.DataFrame(rows)
