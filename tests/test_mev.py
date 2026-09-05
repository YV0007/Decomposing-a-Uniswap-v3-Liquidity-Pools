"""Sandwich classification.

The constraints tested here are the ones that separate a searcher from a router:
same-address bracketing alone fires on any address that trades both ways in one
block. On ETH/USDC 5bp in January 2023 the unconstrained rule returned 2,620
candidates of which 45% lost money; the constrained rule returns 241 with a
median reversal ratio of exactly 1.0.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.build.mev import (AttributionMethod, _reversal_ratio, attribute_to_lp,
                           classify_sandwiches_by_address, gate_sandwich_counts,
                           sandwich_intensity)
from src.utils.config import pool

SPEC = pool("ETH_USDC_5bp")
ATK, VIC, OTHER = "0xattacker", "0xvictim", "0xother"


def _swap(li, sender, a0, a1, block=1):
    return {"block_number": block, "block_timestamp": 100, "log_index": li,
            "sender": sender, "amount0": a0, "amount1": a1,
            "tick": 0, "liquidity": 10**20}


def _frame(rows):
    return pd.DataFrame(rows)


def _textbook_sandwich(block=1):
    """Attacker buys WETH, victim buys at the worse price, attacker sells it back."""
    return [
        _swap(1, ATK, +1_000_000_000, -800_000_000_000_000_000, block),   # in: USDC, out: WETH
        _swap(2, VIC, +500_000_000, -390_000_000_000_000_000, block),
        _swap(3, ATK, -1_050_000_000, +800_000_000_000_000_000, block),   # unwinds exactly
    ]


# --------------------------------------------------------------------------- #
# Reversal ratio — the discriminating constraint
# --------------------------------------------------------------------------- #

def test_reversal_ratio_is_one_for_an_exact_unwind():
    rows = _textbook_sandwich()
    assert _reversal_ratio(rows[0], rows[2]) == pytest.approx(1.0)


def test_reversal_ratio_detects_an_unbalanced_pair():
    """The real false positive: 1.25m USDC sold, 10k bought back."""
    front = _swap(4, ATK, -1_245_885_220_000, +787_753_000_000_000_000_000)
    back = _swap(189, ATK, +10_000_000_000, -6_314_100_000_000_000_000)
    assert _reversal_ratio(front, back) < 0.01


def test_textbook_sandwich_is_detected():
    s = classify_sandwiches_by_address(_frame(_textbook_sandwich()), SPEC)
    assert len(s) == 1
    assert s.iloc[0].attacker == ATK
    assert s.iloc[0].victim_log_indices == (2,)
    assert s.iloc[0].reversal_ratio == pytest.approx(1.0)


def test_unbalanced_pair_is_rejected():
    rows = [
        _swap(1, ATK, -1_245_885_220_000, +787_753_000_000_000_000_000),
        _swap(2, VIC, +500_000_000, -390_000_000_000_000_000),
        _swap(3, ATK, +10_000_000_000, -6_314_100_000_000_000_000),
    ]
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC)) == 0


def test_legs_spanning_the_block_are_rejected():
    rows = _textbook_sandwich()
    rows[2]["log_index"] = 500
    rows[1]["log_index"] = 250
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC, max_leg_span=24)) == 0


def test_a_pair_with_no_victim_between_is_not_a_sandwich():
    rows = [r for r in _textbook_sandwich() if r["sender"] == ATK]
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC)) == 0


def test_same_direction_legs_are_not_a_sandwich():
    rows = _textbook_sandwich()
    rows[2] = _swap(3, ATK, +1_000_000_000, -800_000_000_000_000_000)
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC)) == 0


def test_loss_making_candidates_are_excluded_by_default():
    """A sandwich is profitable by construction; a losing pair is not one."""
    rows = _textbook_sandwich()
    rows[2] = _swap(3, ATK, -900_000_000, +800_000_000_000_000_000)   # unwinds at a loss
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC)) == 0
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC,
                                              require_positive_profit=False)) == 1


def test_sandwiches_do_not_span_blocks():
    rows = _textbook_sandwich(block=1)
    rows[2]["block_number"] = 2
    assert len(classify_sandwiches_by_address(_frame(rows), SPEC)) == 0


# --------------------------------------------------------------------------- #
# Intensity, attribution, gate
# --------------------------------------------------------------------------- #

def test_intensity_counts_both_attacker_legs():
    df = _frame(_textbook_sandwich())
    i = sandwich_intensity(df, classify_sandwiches_by_address(df, SPEC))
    assert i["n_sandwiches"] == 1
    assert i["attacker_swap_share"] == pytest.approx(2 / 3)


def test_neutral_attribution_charges_the_lp_nothing():
    """The LP earns a fee on all three legs and ends near the inventory the
    victim alone would have left it, so the direct P&L effect is ~zero."""
    df = _frame(_textbook_sandwich())
    s = classify_sandwiches_by_address(df, SPEC)
    from decimal import Decimal
    assert attribute_to_lp(s, df, SPEC, Decimal("1400"),
                           AttributionMethod.NEUTRAL) == 0


def test_gate_abstains_on_pools_too_thin_to_test():
    thin = {"n_swaps": 655, "n_sandwiches": 0, "attacker_swap_share": 0.0,
            "sandwiched_block_share": 0.0}
    g = gate_sandwich_counts(thin)
    assert g["passed"] and not g["applicable"]


def test_gate_flags_an_implausibly_high_share():
    busy = {"n_swaps": 200_000, "n_sandwiches": 50_000, "attacker_swap_share": 0.50,
            "sandwiched_block_share": 0.4}
    assert not gate_sandwich_counts(busy)["passed"]
