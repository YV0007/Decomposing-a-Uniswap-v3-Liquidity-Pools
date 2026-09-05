"""Historical gas — actual price at the block, never a period average.

Gas is charged at entry, exit, every re-centring and every hedge rebalance.
An average understates cost in exactly the high-gas periods where a strategy
would have been squeezed, which is the wrong direction for an honest backtest.

Post-London the cost of a transaction is `gas_used * (base_fee + priority_fee)`.
Base fee is read from the block header; priority fee is a behavioural choice, so
it is a stated, swept assumption rather than a measured constant.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.fetch.rpc_client import RPCClient

#: Gas units per action. Measured from typical mainnet receipts; a mint that
#: initialises new ticks costs more than one that reuses initialised ticks, so
#: these are the higher (new-tick) figures — the conservative direction for a
#: cost estimate.
GAS_UNITS = {
    "v3_mint": 450_000,
    "v3_burn": 200_000,
    "v3_collect": 130_000,
    "v3_swap": 180_000,
    "perp_rebalance": 0,      # CEX hedge: no on-chain gas, exchange fees instead
}

#: Priority fee assumption, in gwei. Swept in robustness.
DEFAULT_PRIORITY_GWEI = Decimal("1.5")
GWEI = Decimal(10) ** 9
WEI_PER_ETH = Decimal(10) ** 18


def base_fee_at(client: RPCClient, block: int) -> int:
    """`baseFeePerGas` in wei from the block header."""
    header = client.get_block(block)
    if "baseFeePerGas" not in header:
        raise ValueError(f"block {block} predates EIP-1559")
    return int(header["baseFeePerGas"], 16)


def action_cost_usd(
    client: RPCClient, action: str, block: int, eth_price_usd: Decimal,
    priority_gwei: Decimal = DEFAULT_PRIORITY_GWEI,
) -> Decimal:
    """USD cost of one action at one block, at that block's actual base fee."""
    if action not in GAS_UNITS:
        raise KeyError(f"unknown action {action!r}; known: {sorted(GAS_UNITS)}")
    units = GAS_UNITS[action]
    if units == 0:
        return Decimal(0)
    total_wei = Decimal(units) * (Decimal(base_fee_at(client, block)) + priority_gwei * GWEI)
    return total_wei / WEI_PER_ETH * eth_price_usd


def position_gas_usd(
    client: RPCClient, entry_block: int, exit_block: int,
    entry_eth_price: Decimal, exit_eth_price: Decimal,
    recentre_blocks: list[int] | None = None,
    recentre_prices: list[Decimal] | None = None,
    priority_gwei: Decimal = DEFAULT_PRIORITY_GWEI,
) -> dict:
    """Total gas for a position's lifecycle, priced at each event's own block.

    A re-centring is a burn, a collect and a mint — three transactions, which is
    why frequent re-centring is expensive in a way a single average gas figure
    hides completely.
    """
    events = [("v3_mint", entry_block, entry_eth_price)]
    for blk, px in zip(recentre_blocks or [], recentre_prices or []):
        events += [("v3_burn", blk, px), ("v3_collect", blk, px), ("v3_mint", blk, px)]
    events += [("v3_burn", exit_block, exit_eth_price), ("v3_collect", exit_block, exit_eth_price)]

    breakdown, total = [], Decimal(0)
    for action, blk, px in events:
        cost = action_cost_usd(client, action, blk, px, priority_gwei)
        breakdown.append({"action": action, "block": blk, "cost_usd": float(cost)})
        total += cost
    return {"total_usd": total, "n_transactions": len(events),
            "breakdown": pd.DataFrame(breakdown)}


def base_fee_series(client: RPCClient, blocks: list[int]) -> pd.Series:
    """Base fee for a list of blocks. One RPC call each; sample rather than sweep."""
    return pd.Series({b: base_fee_at(client, b) for b in blocks}, name="base_fee_wei")
