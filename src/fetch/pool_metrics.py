"""Pool-level metrics: TVL, total fee revenue, and the *advertised* APR.

Replaces the planned subgraph fetcher. The Graph's gateway now requires a key,
and everything needed is readable from the chain directly — which is also the
source the subgraph derives from, so this is an upgrade rather than a
workaround. See `DECISIONS.md` 0.4.

The advertised APR matters more than it looks. It is the number an LP is
actually shown on a dashboard, and the paper's headline claim is a comparison
against it. Getting its convention right is therefore part of the argument, not
a detail: quoting a figure no dashboard uses would make the comparison a straw
man.

**Convention used here:** `pool fee revenue over the window / TVL`, annualised.
This is the common dashboard form. Two things about it are worth stating
plainly, because they are exactly why the advertised number overstates what an
LP earns:

1. It divides by *total* TVL, as though every dollar in the pool earned every
   fee. In v3 only liquidity spanning the current tick earns anything, so the
   real per-dollar rate for an in-range position is higher and for an
   out-of-range one is zero. The advertised figure is an average over a
   population most of whose members are not earning.
2. It is gross of LVR, MEV and gas — which is the entire thesis.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.fetch.rpc_client import RPCClient
from src.utils.config import PoolSpec

SEL_BALANCE_OF = "0x70a08231"
SECONDS_PER_YEAR = 365 * 24 * 3600


def token_balance(client: RPCClient, token: str, holder: str, block: int) -> int:
    """ERC-20 `balanceOf` at a historical block, in base units."""
    data = SEL_BALANCE_OF + "0" * 24 + holder[2:].lower()
    return int(client.eth_call(token, data, block=block), 16)


def pool_tvl_usd(
    client: RPCClient, spec: PoolSpec, block: int, pool_price: Decimal
) -> Decimal:
    """Total value locked, from the pool's actual token balances.

    Balances include uncollected fees, which the subgraph's `totalValueLockedUSD`
    also does. Kept consistent rather than corrected, since the point is to
    reproduce the advertised number, not to improve on it.
    """
    from src.build.position import token_usd_prices

    b0 = token_balance(client, spec.token0.address, spec.address, block)
    b1 = token_balance(client, spec.token1.address, spec.address, block)
    p0, p1 = token_usd_prices(spec, pool_price)
    return (
        Decimal(b0) / Decimal(10**spec.token0.decimals) * p0
        + Decimal(b1) / Decimal(10**spec.token1.decimals) * p1
    )


def pool_fee_revenue_usd(
    swaps: pd.DataFrame, spec: PoolSpec, pool_price: Decimal
) -> Decimal:
    """Total fees earned by the whole pool over the swap set.

    The fee is charged on the input token and the event's positive amount is the
    gross transfer, so the fee is exactly `amount_in * fee_rate`.
    """
    from src.build.position import token_usd_prices

    num, den = int(spec.fee_rate * 10**9), 10**9
    f0 = sum(int(a) * num // den for a in swaps["amount0"] if int(a) > 0)
    f1 = sum(int(a) * num // den for a in swaps["amount1"] if int(a) > 0)
    p0, p1 = token_usd_prices(spec, pool_price)
    return (
        Decimal(f0) / Decimal(10**spec.token0.decimals) * p0
        + Decimal(f1) / Decimal(10**spec.token1.decimals) * p1
    )


def advertised_apr(fee_revenue_usd: Decimal, tvl_usd: Decimal, seconds: int) -> Decimal:
    """The number an LP is shown: pool fee revenue over TVL, annualised."""
    if tvl_usd <= 0 or seconds <= 0:
        raise ValueError("TVL and elapsed seconds must be positive")
    return fee_revenue_usd / tvl_usd * Decimal(SECONDS_PER_YEAR) / Decimal(seconds)


def pool_summary(
    client: RPCClient, spec: PoolSpec, swaps: pd.DataFrame,
    start_block: int, end_block: int, start_price: Decimal, end_price: Decimal,
    seconds: int,
) -> dict:
    """TVL at both ends, total fee revenue, and the advertised APR.

    TVL is averaged across the endpoints rather than taken at one of them: on a
    month where the risky asset moved 40%, an endpoint TVL would swing the
    advertised figure by tens of percent purely through the choice of date.
    """
    tvl_start = pool_tvl_usd(client, spec, start_block, start_price)
    tvl_end = pool_tvl_usd(client, spec, end_block, end_price)
    tvl_mean = (tvl_start + tvl_end) / 2
    fees = pool_fee_revenue_usd(swaps, spec, end_price)
    return {
        "pool": spec.id,
        "fee_tier_bps": spec.fee_tier_bps,
        "tvl_start_usd": tvl_start,
        "tvl_end_usd": tvl_end,
        "tvl_mean_usd": tvl_mean,
        "pool_fee_revenue_usd": fees,
        "advertised_apr": advertised_apr(fees, tvl_mean, seconds),
        "n_swaps": len(swaps),
    }
