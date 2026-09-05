"""MEV classification and — the harder half — attribution to the LP.

Sandwich pattern, within one block by `evt_index`::

    tx_A (searcher buys) -> tx_B (victim swap) -> tx_C (searcher sells)

with A and C from the same address, same pool, opposite directions.

**Attribution is open question 1 and is a real modelling decision.** Sandwiching
primarily harms the *trader*, not the LP: the LP earns fees on all three legs.
The LP effect is indirect — sandwich flow is informed flow, and informed flow
degrades the quality of the order flow the LP faces. See DECISIONS.md Q1 for the
three candidate treatments; all three are reported, one leads.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd

from src.utils.config import PoolSpec


class AttributionMethod(str, Enum):
    EXCLUDE_SANDWICH_VOLUME = "exclude_sandwich_volume"   # (a)
    NEUTRAL = "neutral"                                   # (b)
    FLOW_TOXICITY = "flow_toxicity"                       # (c) — working preference


def classify_sandwiches_by_address(swaps: pd.DataFrame, spec: PoolSpec) -> pd.DataFrame:
    """Own classifier: same-address, same-block, opposite-direction bracketing.

    Undercounts, because searchers rotate addresses. Reported as the robustness
    arm, with `classify_sandwiches_by_bundle` as the other bound.
    """
    raise NotImplementedError("Stage 4.1")


def classify_sandwiches_by_bundle(
    swaps: pd.DataFrame, bundles: pd.DataFrame, spec: PoolSpec
) -> pd.DataFrame:
    """Bundle-level identification via Flashbots relay data.

    Catches address rotation that same-address matching misses. Both counts are
    reported; the spread between them is the classification uncertainty.
    """
    raise NotImplementedError("Stage 4.1")


def load_dune_classified(pool_address: str, start: str, end: str) -> pd.DataFrame:
    """Dune's pre-classified MEV tables — the primary source.

    Verify the current schema before use; these tables are renamed periodically.
    """
    raise NotImplementedError("Stage 4.1")


def extracted_value(sandwiches: pd.DataFrame, spec: PoolSpec) -> pd.Series:
    """Value extracted per sandwich, and who it came from."""
    raise NotImplementedError("Stage 4.2")


def attribute_to_lp(
    sandwiches: pd.DataFrame,
    fees: pd.Series,
    method: AttributionMethod = AttributionMethod.FLOW_TOXICITY,
) -> pd.Series:
    """Convert MEV activity into an LP cost under the chosen treatment.

    (a) `EXCLUDE_SANDWICH_VOLUME` — subtract fees earned on sandwich legs from
        "good" fee revenue. Defensible if that volume is not incremental
        uninformed flow.
    (b) `NEUTRAL` — zero. Fees are earned; the LP is indifferent to who trades.
    (c) `FLOW_TOXICITY` — price the adverse selection the sandwich flow imposes,
        separately from the fees it pays. Closest to how a dealer accounts for
        it, and to the companion GEX paper's framing.

    Whichever leads, the other two are reported as bounds and the reasoning is
    written down in DECISIONS.md. This is not a lookup.
    """
    raise NotImplementedError("Stage 4.2 — open question 1")


def gate_sandwich_counts(counts: dict, reference_dashboard: dict) -> dict:
    """Stage 4 GATE: counts within an order of magnitude of published dashboards."""
    raise NotImplementedError("Stage 4.3 — GATE")
