"""Dune Analytics fetcher with local caching.

Queries live as `.sql` files in `dune/` — publishing them is part of the
transparency contribution, so no SQL is inlined in Python. This module reads a
`.sql` file, substitutes parameters, executes it, and caches the result as
parquet under `data/raw/`.

Free tier has execution limits. Cache aggressively; a re-run of the pipeline
must not re-execute a query whose parameters have not changed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DUNE_DIR = Path(__file__).resolve().parents[2] / "dune"

#: Columns required from Pool_evt_Swap. `evt_index` is the within-block
#: ordering needed for sandwich classification — it is never dropped.
SWAP_COLUMNS = [
    "evt_block_number",
    "evt_block_time",
    "evt_tx_hash",
    "evt_index",
    "amount0",
    "amount1",
    "sqrtPriceX96",
    "liquidity",
    "tick",
    "sender",
    "recipient",
]


def run_query(sql_file: str, params: dict, cache: bool = True) -> pd.DataFrame:
    """Execute a query from `dune/` and return it, caching to `data/raw/`.

    Integer-valued on-chain fields (`sqrtPriceX96`, `liquidity`, `amount0`,
    `amount1`) MUST come back as Python ints or strings, never float64. Dune
    returns them as decimal strings; the parquet round trip must preserve that.
    """
    raise NotImplementedError("Stage 1.1")


def fetch_swaps(pool_address: str, start: str, end: str) -> pd.DataFrame:
    """`uniswap_v3_ethereum.Pool_evt_Swap` for one pool over a date range."""
    raise NotImplementedError("Stage 1.1")


def fetch_mints_burns(pool_address: str, start: str, end: str) -> pd.DataFrame:
    """`Pool_evt_Mint` and `Pool_evt_Burn` — needed for fee approach A."""
    raise NotImplementedError("Stage 1.1 / 2.2")


def fetch_sandwiches(pool_address: str, start: str, end: str) -> pd.DataFrame:
    """Dune's pre-classified MEV tables — the primary MEV source (Stage 4.1)."""
    raise NotImplementedError("Stage 4.1")


def assert_no_float_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Guard: raise if any precision-critical column arrived as float.

    Called on every fetch. A float64 `sqrtPriceX96` is the failure mode that
    "matches on day 1 and breaks at scale".
    """
    raise NotImplementedError("Stage 1.1")
