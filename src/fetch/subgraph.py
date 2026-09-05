"""Uniswap v3 subgraph — the validation oracle for Stages 1 and 2.

The subgraph is not a data source for the analysis; it is the independent
reference the reconstruction is checked against. H1 is a GO/NO-GO on exactly
this comparison.
"""

from __future__ import annotations

import pandas as pd

SUBGRAPH_URL = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"


def fetch_pool_day_data(pool_address: str, start: str, end: str) -> pd.DataFrame:
    """Daily TVL, volume, fees and price from the subgraph.

    Columns: `[date, tvl_usd, volume_usd, fees_usd, tx_count, liquidity]`.
    """
    raise NotImplementedError("Stage 1.4")


def fetch_swap_count(pool_address: str, start: str, end: str) -> int:
    """Swap count for a period — the Stage 1 gate compares against this."""
    raise NotImplementedError("Stage 1.4")


def fetch_fee_growth_global(pool_address: str, block: int) -> tuple[int, int]:
    """`feeGrowthGlobal0X128`, `feeGrowthGlobal1X128` at a block.

    The Stage 2 gate derives realised fees from the change in these across the
    period and requires the simulated accrual to match within 2%.
    """
    raise NotImplementedError("Stage 2.3")


def fetch_advertised_apr(pool_address: str, start: str, end: str) -> pd.Series:
    """The number LPs are actually shown — the comparison column of Output 1.

    Conventionally `fees_usd / tvl_usd` annualised. The convention used by the
    dashboard being quoted must be recorded, since dashboards differ and the
    headline claim is a comparison against it.
    """
    raise NotImplementedError("Stage 5.3")
