"""No-lookahead tests. The property is asserted, not assumed.

Lookahead is the failure mode that produces a good-looking result rather than
an error, so it is the one that must be caught mechanically. These tests cover
the alignment layer now; the feature-matrix half is the Stage 6 gate and is
marked xfail until `src.model.features` is implemented.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.build.align import (LOOKAHEAD_RULES, AlignmentRule, align_cex_to_blocks,
                             assert_causal)

#: Blocks on the 12s beacon grid.
BLOCKS = pd.DataFrame(
    {
        "block_number": [100, 101, 102, 103],
        "block_timestamp": [1_672_531_200, 1_672_531_212, 1_672_531_224, 1_672_531_236],
        "price": ["1200.00", "1201.00", "1199.00", "1202.00"],
    }
)

#: One kline per second across the span.
CEX = pd.DataFrame(
    {
        "second": list(range(1_672_531_190, 1_672_531_250)),
        "close": [str(1200 + i * 0.1) for i in range(60)],
    }
)


def test_baseline_rule_is_strictly_causal():
    aligned = align_cex_to_blocks(BLOCKS, CEX, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert_causal(aligned)


def test_matched_kline_closes_before_the_block():
    """A kline opening at `s` closes in [s, s+1), so `s + 1 <= block_ts` is required.

    Matching the kline for second `block_ts` itself would admit up to one
    second of lookahead — its close could be a trade at `block_ts + 0.9`, which
    did not exist when the block was built.
    """
    aligned = align_cex_to_blocks(BLOCKS, CEX, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert (aligned["cex_second"] + 1 <= aligned["block_timestamp"]).all()
    assert (aligned["cex_second"] == aligned["block_timestamp"] - 1).all()


def test_one_slot_earlier_is_also_causal():
    """Deliberately staler, still causal.

    The first block has no admissible reference (the key falls before the CEX
    series starts), so it is correctly left unmatched rather than filled from
    a later observation — checked on matched rows only.
    """
    aligned = align_cex_to_blocks(BLOCKS, CEX, AlignmentRule.ONE_SLOT_EARLIER)
    assert_causal(aligned)
    matched = aligned[aligned["cex_second"].notna()]
    assert len(matched) >= 3
    assert (matched["staleness_seconds"] >= 12).all()


def test_midpoint_rule_is_flagged_and_refused():
    """The interpolating variant peeks forward and must never reach a headline.

    It exists only to quantify how much the answer moves, so it is flagged in
    its own output and `assert_causal` refuses it outright.
    """
    aligned = align_cex_to_blocks(BLOCKS, CEX, AlignmentRule.MIDPOINT_INTERPOLATION)
    assert aligned["uses_lookahead"].all()
    assert (aligned["cex_second"] > aligned["block_timestamp"]).any(), (
        "the midpoint rule should demonstrably reach past the block"
    )
    with pytest.raises(AssertionError, match="lookahead"):
        assert_causal(aligned)


def test_assert_causal_catches_a_forward_match():
    """Hand-built violation: the guard must not depend on the merge direction."""
    aligned = align_cex_to_blocks(BLOCKS, CEX, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    aligned.loc[0, "cex_second"] = aligned.loc[0, "block_timestamp"]
    with pytest.raises(AssertionError, match="postdate"):
        assert_causal(aligned)


def test_no_backward_fill_across_a_gap():
    """A block with no prior CEX observation gets null, never a future price."""
    late_cex = CEX[CEX["second"] >= 1_672_531_230]
    aligned = align_cex_to_blocks(BLOCKS, late_cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert aligned.loc[aligned["block_timestamp"] < 1_672_531_231, "cex_price"].isna().all()
    assert_causal(aligned)


def test_lookahead_rule_registry_is_honest():
    """Every rule is classified; the registry is what `assert_causal` trusts."""
    assert AlignmentRule.MIDPOINT_INTERPOLATION in LOOKAHEAD_RULES
    assert AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS not in LOOKAHEAD_RULES
    assert AlignmentRule.ONE_SLOT_EARLIER not in LOOKAHEAD_RULES


def test_feature_matrix_gate_is_wired_and_fires():
    """Stage 6 GATE. Must pass before any model result is believed.

    Checked both ways round on a realistic weekly panel: a clean matrix passes,
    and a matrix carrying the target fails. A gate that cannot fail is not
    evidence, so both directions are asserted. Fuller coverage in
    `tests/test_infra.py`.
    """
    import numpy as np

    from src.model.features import assert_no_lookahead

    rng = np.random.default_rng(11)
    n = 150
    idx = pd.date_range("2023-01-01", periods=n, freq="W", tz="UTC")
    target = pd.Series(rng.normal(scale=0.02, size=n), index=idx)

    clean = pd.DataFrame(
        {
            "realized_vol_7d": np.abs(rng.normal(0.5, 0.1, n)),
            "fee_tier_bps": 30,
            "gas_price_median_7d": np.abs(rng.normal(25, 6, n)),
        },
        index=idx,
    )
    assert assert_no_lookahead(clean, target)["passed"]

    leaking = clean.assign(oops=target + rng.normal(scale=0.001, size=n))
    with pytest.raises(AssertionError, match="no-lookahead gate FAILED"):
        assert_no_lookahead(leaking, target)
