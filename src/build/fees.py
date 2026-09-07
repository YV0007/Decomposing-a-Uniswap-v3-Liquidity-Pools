"""Fee accrual for a simulated position.

Fees accrue **only while the position is in range**, pro-rata to its share of
the active liquidity at that tick. Accruing while out of range is the single
most common way to overstate LP returns.

Three methods, not two
----------------------
The plan specifies two approaches — replaying every Mint/Burn to rebuild the
tick liquidity map (A), or using the `liquidity` field carried on each Swap
event (B). There is a third that is strictly better as a *reference*, and it is
the one used here for validation:

    C — feeGrowthInside, read from the pool contract at historical blocks.

Uniswap v3 accounts fees exactly as

    fees = L * (feeGrowthInside_end - feeGrowthInside_start) / 2**128

where `feeGrowthInside` is derived from `feeGrowthGlobal` and the
`feeGrowthOutside` values stored on the range's two boundary ticks. Reading
those four values at the entry and exit blocks reproduces the contract's own
arithmetic exactly, in four `eth_call`s, with no replay and no approximation.
It is also what the subgraph derives its own figures from, so validating against
it is validating against the source rather than a copy.

Approach B remains necessary: `feeGrowthInside` can only be read for a range
that has already happened, so a forecast, a sweep over hypothetical range
widths, or a backtest of an unrealised position all need the replay. B is what
the pipeline uses; C is what proves B is right.

**C is not always available.** `feeGrowthOutside` is stored per tick and is reset
whenever a tick flips from uninitialized to initialized. If either boundary tick
loses all its liquidity and is later re-initialized between the two readings,
the second reading is measured from a different epoch than the first and their
difference is meaningless — it typically underflows into a number near 2**256.

That is not hypothetical: on ETH/USDC 5bp (10-tick spacing, heavy LP churn) a
boundary tick's gross liquidity moved by a factor of a million within March 2023
and the naive difference implied fees of 8.7e48 dollars. So C is a **spot check
that works when the boundary ticks are stable**, not a universal reference, and
`fees_exact` raises rather than returning a wrapped number when it is not
applicable.
"""


from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.build.position import Position, RangeState, range_state
from src.fetch.rpc_client import RPCClient
from src.utils.config import PoolSpec

Q128 = 1 << 128
UINT256 = 1 << 256

#: keccak selectors on the v3 pool.
SEL_FEE_GROWTH_GLOBAL_0 = "0xf3058399"
SEL_FEE_GROWTH_GLOBAL_1 = "0x46141319"
SEL_TICKS = "0xf30dba93"


class FeeGrowthUnavailable(RuntimeError):
    """Raised when `feeGrowthInside` cannot be differenced across two blocks.

    Means a boundary tick was re-initialized in between, resetting its
    `feeGrowthOutside`. The position's fees are still well defined; they just
    cannot be recovered from two point readings, and approach A (event replay)
    would be needed to validate that period.
    """


# --------------------------------------------------------------------------- #
# Approach C — the contract's own arithmetic
# --------------------------------------------------------------------------- #

def _sub256(a: int, b: int) -> int:
    """uint256 subtraction with wraparound.

    The wrap is intentional in Uniswap's accounting: `feeGrowthInside` is
    permitted to underflow and the difference between two readings is still
    correct modulo 2**256. Doing this in Python's unbounded integers without
    the mask would produce a large negative number instead.
    """
    return (a - b) % UINT256


def read_fee_growth_global(client: RPCClient, pool_address: str, block: int) -> tuple[int, int]:
    g0 = int(client.eth_call(pool_address, SEL_FEE_GROWTH_GLOBAL_0, block=block), 16)
    g1 = int(client.eth_call(pool_address, SEL_FEE_GROWTH_GLOBAL_1, block=block), 16)
    return g0, g1


def read_tick_fee_growth_outside(
    client: RPCClient, pool_address: str, tick: int, block: int
) -> tuple[int, int]:
    """`feeGrowthOutside0X128` and `feeGrowthOutside1X128` for one tick.

    `ticks(int24)` returns eight values; the two fee-growth words are at
    offsets 2 and 3. The tick argument is sign-extended to a full word, as the
    ABI requires for a negative int24.
    """
    arg = format(tick % UINT256, "064x")
    raw = client.eth_call(pool_address, SEL_TICKS + arg, block=block)
    body = raw[2:]
    word = lambda i: int(body[i * 64 : (i + 1) * 64], 16)
    return word(2), word(3)


def fee_growth_inside(
    client: RPCClient, pool_address: str, tick_lower: int, tick_upper: int,
    tick_current: int, block: int,
) -> tuple[int, int]:
    """`feeGrowthInside` for a range, exactly as `Tick.getFeeGrowthInside` does."""
    g0, g1 = read_fee_growth_global(client, pool_address, block)
    lo0, lo1 = read_tick_fee_growth_outside(client, pool_address, tick_lower, block)
    hi0, hi1 = read_tick_fee_growth_outside(client, pool_address, tick_upper, block)

    if tick_current >= tick_lower:
        below0, below1 = lo0, lo1
    else:
        below0, below1 = _sub256(g0, lo0), _sub256(g1, lo1)

    if tick_current < tick_upper:
        above0, above1 = hi0, hi1
    else:
        above0, above1 = _sub256(g0, hi0), _sub256(g1, hi1)

    return _sub256(_sub256(g0, below0), above0), _sub256(_sub256(g1, below1), above1)


#: A month of fee growth on a busy pool sits around 1e30-1e33 in X128 units.
#: A wrapped underflow lands near 2**256 ~ 1.2e77, so anything above this
#: threshold is an epoch mismatch rather than a large month.
_FEE_GROWTH_SANITY_CEILING = 1 << 200


def fees_exact(
    client: RPCClient, spec: PoolSpec, position: Position,
    block_start: int, tick_start: int, block_end: int, tick_end: int,
) -> tuple[int, int]:
    """Reference fee accrual, in token base units, from the contract's own state.

    Four `eth_call`s per endpoint, no replay, no approximation — when it is
    applicable. Raises :class:`FeeGrowthUnavailable` when a boundary tick was
    re-initialized between the two blocks, because the difference is then a
    wrapped underflow rather than a fee.
    """
    i0_s, i1_s = fee_growth_inside(
        client, spec.address, position.tick_lower, position.tick_upper, tick_start, block_start
    )
    i0_e, i1_e = fee_growth_inside(
        client, spec.address, position.tick_lower, position.tick_upper, tick_end, block_end
    )
    d0, d1 = _sub256(i0_e, i0_s), _sub256(i1_e, i1_s)
    for name, delta in (("token0", d0), ("token1", d1)):
        if delta > _FEE_GROWTH_SANITY_CEILING:
            raise FeeGrowthUnavailable(
                f"feeGrowthInside for {name} decreased across blocks "
                f"{block_start}->{block_end} on {spec.id} (wrapped delta {delta:.3e}). "
                f"A boundary tick of range [{position.tick_lower}, "
                f"{position.tick_upper}] was almost certainly re-initialized in "
                f"between, resetting its feeGrowthOutside. Validate this period "
                f"with approach A instead."
            )
    return position.liquidity * d0 // Q128, position.liquidity * d1 // Q128


# --------------------------------------------------------------------------- #
# Approach B — replay from swap events
# --------------------------------------------------------------------------- #

def _boundary_fraction(pre_tick: int, post_tick: int, position: Position) -> Decimal:
    """Fraction of a swap's tick path that lay inside the position's range.

    A single swap can carry the price from inside the range to outside it. The
    naive test — is the *post-swap* tick in range? — gives that swap zero credit
    for the part of its path that was still earning, and a swap entering the
    range full credit for a path that was mostly outside.

    Measured empirically on ETH/USDC 30bp, January 2023: the naive test is
    accurate to under 0.5% while the position stays inside the range, and the
    whole -1.88% full-period error came from one boundary-crossing swap on the
    day the position exited. Pro-rating by the traversed tick span removes most
    of it.

    The pro-rating is linear in tick space, which is an approximation: fees
    accrue with the liquidity actually traversed, and that is not uniform across
    ticks. It is a first-order correction to a first-order method, and the gate
    against `feeGrowthInside` is what says whether it is good enough.
    """
    lo, hi = (pre_tick, post_tick) if pre_tick <= post_tick else (post_tick, pre_tick)
    if lo == hi:
        return Decimal(1) if range_state(position, post_tick) is RangeState.IN_RANGE else Decimal(0)
    overlap = min(hi, position.tick_upper) - max(lo, position.tick_lower)
    if overlap <= 0:
        return Decimal(0)
    return Decimal(overlap) / Decimal(hi - lo)


def accrue_fees_approach_b(
    swaps: pd.DataFrame, position: Position, spec: PoolSpec,
    entry_tick: int | None = None, split_boundary: bool = True,
    deposited: bool = True,
) -> pd.DataFrame:
    """Per-swap fee accrual from the `liquidity` field on each Swap event.

    The fee is charged on the **input** token, and the event's positive amount
    is the gross transfer, which already includes the fee — so the fee is
    exactly `amount_in * fee_rate`, not `amount_in * fee_rate / (1 - fee_rate)`.

    **Two different shares, and which is right depends on the question.**

    - `deposited=True` (default) — `L / (L_active + L)`. The share an LP who
      actually deposits receives, because their own liquidity joins the
      denominator. This is what the paper simulates.
    - `deposited=False` — `L / L_active`. The share of an infinitesimal
      position that does *not* join the pool, which is how the pool increments
      `feeGrowthGlobal` (by `feeAmount / L_active`). Use this when validating
      against `feeGrowthInside`, or the gate compares two different quantities.

    The gap is the position's own liquidity share, so it is negligible where the
    position is small and decisive where it is not. Measured at $100k: 0.09% of
    active liquidity on ETH/USDC 5bp, 0.32% on 30bp, and **22.6% on 100bp** —
    where ignoring it overstates fees by more than a fifth, and where the
    position is in any case large enough to move the pool price, which no fee
    correction repairs.

    Known source of divergence from the exact method: `liquidity` on the event
    is the active liquidity **after** the swap settles, so a swap that crossed
    ticks earned its fees across several liquidity levels. That is the main
    thing the Stage 2 gate is testing.
    """
    fee_rate = spec.fee_rate
    num = int(fee_rate * 10**9)          # exact integer arithmetic on the fee
    den = 10**9

    rows = []
    prev_tick = entry_tick
    for blk, ts, tick, liq, a0, a1 in zip(
        swaps["block_number"], swaps["block_timestamp"], swaps["tick"],
        swaps["liquidity"], swaps["amount0"], swaps["amount1"],
    ):
        tick = int(tick)
        if prev_tick is None:
            prev_tick = tick
        in_range = range_state(position, tick) is RangeState.IN_RANGE
        frac = (
            _boundary_fraction(prev_tick, tick, position)
            if split_boundary
            else (Decimal(1) if in_range else Decimal(0))
        )
        f0 = f1 = 0
        if frac > 0 and int(liq) > 0:
            denom = int(liq) + (position.liquidity if deposited else 0)
            if int(a0) > 0:
                f0 = int(Decimal(int(a0) * num // den * position.liquidity // denom) * frac)
            if int(a1) > 0:
                f1 = int(Decimal(int(a1) * num // den * position.liquidity // denom) * frac)
        rows.append(
            {
                "block_number": int(blk), "block_timestamp": int(ts), "tick": tick,
                "in_range": in_range, "path_fraction": float(frac), "fee0": f0, "fee1": f1,
            }
        )
        prev_tick = tick
    return pd.DataFrame(rows)


def fees_to_usd(fees0: int, fees1: int, spec: PoolSpec, pool_price: Decimal,
                numeraire_usd: Decimal | None = None) -> Decimal:
    """Convert base-unit fee amounts to USD at the prevailing pool price.

    `numeraire_usd` is required for a pool with no stablecoin leg; without it
    the amounts would be denominated in token1 and silently compared against
    dollar-denominated gas.
    """
    from src.build.position import token_usd_prices

    p0, p1 = token_usd_prices(spec, pool_price, numeraire_usd)
    return (
        Decimal(fees0) / Decimal(10**spec.token0.decimals) * p0
        + Decimal(fees1) / Decimal(10**spec.token1.decimals) * p1
    )


# --------------------------------------------------------------------------- #
# Stage 2 gate
# --------------------------------------------------------------------------- #

def gate_fee_accrual(
    replay_fees: tuple[int, int], exact_fees: tuple[int, int],
    tolerance: Decimal = Decimal("0.02"),
) -> dict:
    """Stage 2 GATE: replayed accrual within 2% of the contract's own figure.

    Failure means stop and diagnose. Replayed fees far *above* the reference
    almost always mean accrual while out of range.
    """
    out = {"tolerance": float(tolerance), "passed": True}
    for i, name in ((0, "token0"), (1, "token1")):
        rep, exa = replay_fees[i], exact_fees[i]
        rel = None if exa == 0 else (Decimal(rep) - Decimal(exa)) / Decimal(exa)
        out[f"{name}_replay"] = rep
        out[f"{name}_exact"] = exa
        out[f"{name}_rel_error"] = None if rel is None else float(rel)
        if rel is not None and abs(rel) > tolerance:
            out["passed"] = False
    return out
