"""End-to-end assembly for one pool over one period.

Chains the stages: swaps -> pool state -> CEX alignment -> position -> fees ->
LVR -> gas -> decomposition row. Kept as a module rather than a script so the
same path is exercised by tests, by the decomposition table, and later by the
backtest.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks, assert_causal
from src.build.decomposition import Decomposition, build_row
from src.build.fees import accrue_fees_approach_b, fees_exact, fees_to_usd
from src.build.lvr import compute_lvr
from src.build.pool_state import build_pool_state
from src.build.position import open_position, simulate
from src.fetch.gas import position_gas_usd
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.model.volatility import align_to_blocks, realized_variance, to_sampled_prices
from src.utils.config import PoolSpec


def run_pool_period(
    spec: PoolSpec, from_block: int, to_block: int, cex: pd.DataFrame,
    notional_usd: Decimal, half_width: Decimal, client: RPCClient | None = None,
    lvr_measure: str = "cex_path", verbose: bool = True,
) -> tuple[Decomposition, dict]:
    """Full decomposition for one pool over one block range.

    Returns the assembled row plus the intermediate artefacts, so a caller can
    inspect the fee gate, the LVR series or the simulation without re-running.
    """
    client = client or RPCClient()
    notes: list[str] = []

    swaps = load_big_ints(fetch_swaps(spec.address, from_block, to_block, client=client))
    state = build_pool_state(swaps, spec)
    if state.empty:
        raise ValueError(f"{spec.id}: no swaps in blocks {from_block}-{to_block}")

    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert_causal(aligned)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)

    px = to_sampled_prices(cex, sample_minutes=5)
    vol = align_to_blocks(realized_variance(px), aligned["block_timestamp"])

    entry = aligned.iloc[0]
    pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                        Decimal(str(entry.price)), notional_usd, half_width)
    sim = simulate(state, pos, spec)

    # Time-weighted, not block-weighted. Pools trade at different frequencies,
    # so "share of traded blocks in range" is not comparable across a fee-tier
    # cross-section: the 5bp pool trades ~350x more often than the 100bp pool
    # over the same price path, which would make the two look different when
    # the position's actual in-range *time* is nearly identical.
    dt = sim["block_timestamp"].diff().shift(-1).fillna(0).clip(lower=0)
    span = max(1, int(sim["block_timestamp"].iloc[-1] - sim["block_timestamp"].iloc[0]))
    share_in_range = Decimal(str(float(dt[sim["in_range"]].sum()) / span))
    if verbose:
        print(f"  {spec.id}: {len(swaps):,} swaps, {len(aligned):,} aligned blocks, "
              f"in range {float(share_in_range):.1%} of time "
              f"({sim.in_range.mean():.1%} of traded blocks)", flush=True)

    # --- fees: replay for the number, contract state for the check ---------- #
    after = swaps[swaps["block_number"] > int(entry.block_number)]
    replay = accrue_fees_approach_b(after, pos, spec, entry_tick=int(entry.tick),
                                     deposited=False)  # gate compares against feeGrowthInside
    rep0, rep1 = int(replay.fee0.sum()), int(replay.fee1.sum())
    end = aligned.iloc[-1]
    exa0, exa1 = fees_exact(client, spec, pos, int(entry.block_number), int(entry.tick),
                            int(end.block_number), int(end.tick))
    exit_price = Decimal(str(end.price))
    fees_usd = fees_to_usd(rep0, rep1, spec, exit_price)
    fee_check = {
        "replay_usd": float(fees_usd),
        "exact_usd": float(fees_to_usd(exa0, exa1, spec, exit_price)),
    }
    fee_check["rel_error"] = (
        None if fee_check["exact_usd"] == 0
        else fee_check["replay_usd"] / fee_check["exact_usd"] - 1
    )
    if fee_check["rel_error"] is not None and abs(fee_check["rel_error"]) > 0.02:
        notes.append(f"fee gate breached: {fee_check['rel_error']:+.2%}")

    lvr = compute_lvr(aligned, pos, spec, vol)

    gas = position_gas_usd(
        client, int(entry.block_number), int(end.block_number),
        Decimal(str(entry.price)), exit_price,
    )

    row = build_row(
        pool_id=spec.id, fee_tier_bps=spec.fee_tier_bps, lvr_result=lvr,
        fees_usd=fees_usd, gas_usd=gas["total_usd"], mev_usd=Decimal(0),
        funding_usd=Decimal(0), share_in_range=share_in_range,
        period_start=pd.Timestamp(int(entry.block_timestamp), unit="s", tz="UTC"),
        period_end=pd.Timestamp(int(end.block_timestamp), unit="s", tz="UTC"),
        variant="raw", lvr_measure=lvr_measure,
        notes=notes + ["MEV not yet attributed — Stage 4 pending"],
    )
    return row, {"state": state, "aligned": aligned, "position": pos, "sim": sim,
                 "lvr": lvr, "gas": gas, "fee_check": fee_check,
                 "share_in_range_blocks": Decimal(str(sim.in_range.mean()))}
