"""Historical gas — actual price at the block, never a period average.

Gas is charged at entry, exit, every re-centring and every hedge rebalance.
Using an average understates cost in exactly the high-gas periods where the
strategy would have been squeezed, which is the wrong direction for an honest
backtest.
"""

from __future__ import annotations

import pandas as pd

#: Approximate gas units. Refine against observed receipts before Stage 5.
GAS_UNITS = {
    "v3_mint": 450_000,
    "v3_burn": 350_000,
    "v3_collect": 130_000,
    "v3_swap": 180_000,
}


def fetch_block_gas(start_block: int, end_block: int) -> pd.DataFrame:
    """Per-block `base_fee_per_gas` and timestamp from `ethereum.blocks`."""
    raise NotImplementedError("Stage 1.1")


def cost_usd(action: str, block: int, eth_price: "object") -> "object":
    """USD cost of one action at one block, at that block's actual gas price."""
    raise NotImplementedError("Stage 5.1")


def total_gas_cost(events: pd.DataFrame, gas: pd.DataFrame, eth_price: pd.Series) -> pd.Series:
    """Gas cost per period for a position's full event list."""
    raise NotImplementedError("Stage 5.1")
