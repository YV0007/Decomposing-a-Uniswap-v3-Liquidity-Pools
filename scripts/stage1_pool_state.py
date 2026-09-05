"""Stage 1 — reconstruct one pool's state for one month, and run the gate.

One pool, one month, end to end, before scaling anything.

Gate: every reconstructed price must lie inside the one-basis-point band
implied by the tick the pool itself emitted. Independently, `slot0()` read at a
historical block must return exactly the `sqrtPriceX96` carried by that block's
last Swap log.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.pool_state import (attach_block_times, build_pool_state,
                                  gate_price_reconstruction)
from src.fetch.rpc_client import RPCClient, block_at_or_before, fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

POOL_ID = "ETH_USDC_30bp"
MONTH_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
MONTH_END = datetime(2023, 2, 1, tzinfo=timezone.utc)
SLOT0_SELECTOR = "0x3850c7bd"


def main() -> int:
    spec = pool(POOL_ID)
    spec.require_verified()
    client = RPCClient()

    print(f"=== Stage 1: {POOL_ID} {MONTH_START:%Y-%m-%d} -> {MONTH_END:%Y-%m-%d} ===\n")

    print("resolving block range...")
    b0 = block_at_or_before(client, int(MONTH_START.timestamp()))
    b1 = block_at_or_before(client, int(MONTH_END.timestamp()))
    print(f"  blocks {b0} -> {b1}  ({b1 - b0:,} blocks)\n")

    swaps = load_big_ints(fetch_swaps(spec.address, b0, b1, client=client))
    print(f"\n  {len(swaps):,} swaps decoded")
    print(f"  types: sqrt_price_x96={type(swaps['sqrt_price_x96'].iloc[0]).__name__}, "
          f"amount0={type(swaps['amount0'].iloc[0]).__name__}\n")

    state = build_pool_state(swaps, spec)
    print(f"  {len(state):,} blocks with trades")
    print(f"  price range: {min(state['price']):.2f} - {max(state['price']):.2f} USD/ETH\n")

    print("--- GATE 1a: price vs the pool's own tick (1bp band) ---")
    g = gate_price_reconstruction(state, spec)
    print(f"  rows checked          : {g['n_rows']:,}")
    print(f"  outside the tick band : {g['n_outside_tick_band']}")
    print(f"  position within tick  : [{g['min_position_in_tick']:.6f}, {g['max_position_in_tick']:.6f}]")
    print(f"  -> {'PASS' if g['passed'] else 'FAIL'}\n")

    print("--- GATE 1b: slot0() at historical blocks vs the log ---")
    sample = state.sample(n=min(10, len(state)), random_state=42).sort_values("block_number")
    n_match = 0
    for _, row in sample.iterrows():
        bn = int(row["block_number"])
        raw = client.eth_call(spec.address, SLOT0_SELECTOR, block=bn)
        onchain_sqrt = int(raw[2:66], 16)
        ok = onchain_sqrt == int(row["sqrt_price_x96"])
        n_match += ok
        print(f"  block {bn}  log={str(row['sqrt_price_x96'])[:24]}...  "
              f"slot0={str(onchain_sqrt)[:24]}...  {'MATCH' if ok else 'MISMATCH'}")
    print(f"  -> {n_match}/{len(sample)} exact  {'PASS' if n_match == len(sample) else 'FAIL'}\n")

    print("resolving block timestamps for traded blocks (sampled)...")
    times = {int(b): client.block_timestamp(int(b)) for b in state["block_number"].head(3)}
    state_t = attach_block_times(state.head(3), times)
    print(state_t[["block_number", "block_dt", "price", "tick", "n_swaps"]].to_string(index=False))

    out = REPO_ROOT / "data" / "interim"
    out.mkdir(parents=True, exist_ok=True)
    save = state.copy()
    for c in ("sqrt_price_x96", "liquidity", "volume0", "volume1"):
        save[c] = save[c].map(str)
    save["price"] = save["price"].map(str)
    dest = out / f"pool_state_{POOL_ID}_2023-01.parquet"
    save.to_parquet(dest, index=False)
    print(f"\nwrote {dest.relative_to(REPO_ROOT)}")

    passed = g["passed"] and n_match == len(sample)
    print(f"\n=== STAGE 1 GATE: {'PASS — proceed to Stage 2' if passed else 'FAIL — stop and diagnose'} ===")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
