"""Stage 1.3/1.4 — align the CEX reference to blocks and measure the gap.

The gap between the pool price and the CEX price at the same instant is what
an arbitrageur trades against, and it is the raw material of empirical LVR.
This script produces the first economic quantity in the project, and checks the
alignment is strictly causal before it does.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.align import (AlignmentRule, align_cex_to_blocks, alignment_sensitivity,
                             assert_causal, price_gap)
from src.build.pool_state import build_pool_state
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

POOL_ID, B0, B1 = "ETH_USDC_30bp", 16308189, 16530247


def main() -> int:
    spec = pool(POOL_ID)
    spec.require_verified()

    swaps = load_big_ints(fetch_swaps(spec.address, B0, B1, client=RPCClient()))
    state = build_pool_state(swaps, spec)
    cex = load_klines_1s("ETHUSDT", 2023, 1)
    print(f"\npool blocks: {len(state):,}   cex klines: {len(cex):,}\n")

    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)

    print("--- causality check ---")
    assert_causal(aligned)
    print("  PASS: every reference closes strictly before its block\n")

    matched = aligned["cex_price"].notna()
    print(f"  matched {matched.sum():,}/{len(aligned):,} blocks "
          f"({100*matched.mean():.3f}%)")
    print(f"  staleness (s): median={aligned['staleness_seconds'].median():.0f}  "
          f"p99={aligned['staleness_seconds'].quantile(0.99):.0f}  "
          f"max={aligned['staleness_seconds'].max():.0f}\n")

    aligned["gap"] = price_gap(aligned)
    g = pd.Series([float(x) for x in aligned["gap"].dropna()])
    print("--- pool vs CEX price gap (bp) ---")
    print(f"  mean       {g.mean()*1e4:+8.3f}")
    print(f"  median     {g.median()*1e4:+8.3f}")
    print(f"  mean |gap| {g.abs().mean()*1e4:8.3f}")
    print(f"  p50 |gap|  {g.abs().quantile(.50)*1e4:8.3f}")
    print(f"  p95 |gap|  {g.abs().quantile(.95)*1e4:8.3f}")
    print(f"  p99 |gap|  {g.abs().quantile(.99)*1e4:8.3f}")
    print(f"  max |gap|  {g.abs().max()*1e4:8.3f}")
    fee_bps = float(spec.fee_rate) * 1e4
    print(f"\n  pool fee = {fee_bps:.0f} bp; share of blocks with |gap| > fee: "
          f"{100*(g.abs()*1e4 > fee_bps).mean():.2f}%")
    print(f"  (arbitrage only fires above fee + gas, so this is an upper bound "
          f"on arbitrageable blocks)\n")

    print("--- open question 3: alignment sensitivity ---")
    sens = alignment_sensitivity(state, cex)
    print(sens.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    sens.to_csv(out / "alignment_sensitivity_2023-01.csv", index=False)
    keep = aligned[["block_number", "block_timestamp", "price", "cex_price",
                    "cex_second", "staleness_seconds", "tick", "n_swaps"]].copy()
    keep["price"] = keep["price"].map(str)
    keep["cex_price"] = keep["cex_price"].map(lambda v: str(v) if v is not None else None)
    keep["gap"] = aligned["gap"].map(lambda v: str(v) if v is not None else None)
    dest = REPO_ROOT / "data" / "interim" / f"aligned_{POOL_ID}_2023-01.parquet"
    keep.to_parquet(dest, index=False)
    print(f"\nwrote {dest.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
