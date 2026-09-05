"""Flashbots relay and bundle data — bundle-level MEV identification.

Same-address sandwich matching undercounts because searchers rotate addresses.
Bundle-level identification catches more. Both counts are reported (Stage 4.1).
"""

from __future__ import annotations

import pandas as pd

RELAY_DATA_URL = "https://boost-relay.flashbots.net/relay/v1/data"


def fetch_delivered_payloads(start_block: int, end_block: int) -> pd.DataFrame:
    """Builder payments per block — proposer payment as an MEV intensity proxy."""
    raise NotImplementedError("Stage 4.1")


def fetch_bundles(start_block: int, end_block: int) -> pd.DataFrame:
    """Bundle composition, for grouping transactions by searcher intent."""
    raise NotImplementedError("Stage 4.1")


def label_transactions_by_bundle(swaps: pd.DataFrame, bundles: pd.DataFrame) -> pd.DataFrame:
    """Attach a bundle id to each swap. Adds `bundle_id`, `bundle_position`."""
    raise NotImplementedError("Stage 4.1")
