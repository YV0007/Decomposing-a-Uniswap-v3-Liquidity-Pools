"""Two falsifiable checks on the price-gap measurement.

**Check 1 — the fee-tier band.** Arbitrage only fires once the pool/CEX gap
exceeds the fee. So the 5bp pool must be held in a visibly tighter band than
the 30bp pool over the same period, on the same asset. If both show the same
dispersion, the pipeline is measuring noise rather than the no-arbitrage band.
This is the mechanism H4 rests on, tested before anything is built on it.

**Check 2 — the stablecoin basis.** The pool quotes ETH in USDC; the Binance
reference quotes ETH in USDT. Any USDC/USDT basis enters the measured gap as a
constant bias that has nothing to do with AMM staleness. Binance published no
ETHUSDC or USDCUSDT series for this period, so the basis is measured on-chain
from the USDC/USDT 1bp pool — the tightest venue for exactly that pair — and
divided out.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks, assert_causal
from src.build.pool_state import build_pool_state
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

B0, B1 = 16308189, 16530247
client = RPCClient()


def state_for(pool_id: str) -> pd.DataFrame:
    spec = pool(pool_id)
    spec.require_verified()
    sw = load_big_ints(fetch_swaps(spec.address, B0, B1, client=client))
    st = build_pool_state(sw, spec)
    print(f"  {pool_id:16s} {len(sw):7,} swaps  {len(st):7,} blocks  "
          f"price {min(st['price']):.4f}-{max(st['price']):.4f}")
    return st


def gap_stats(label: str, pool_price, cex_price) -> dict:
    g = pd.Series([float((c - p) / p) * 1e4 for p, c in zip(pool_price, cex_price)])
    return {
        "series": label, "n": len(g), "mean_bp": g.mean(), "median_bp": g.median(),
        "mean_abs_bp": g.abs().mean(), "p50_abs_bp": g.abs().quantile(.50),
        "p95_abs_bp": g.abs().quantile(.95), "p99_abs_bp": g.abs().quantile(.99),
    }


def main() -> int:
    print("=== fetching pool states (Jan 2023) ===")
    s30 = state_for("ETH_USDC_30bp")
    s05 = state_for("ETH_USDC_5bp")
    sus = state_for("USDC_USDT_1bp")

    cex = load_klines_1s("ETHUSDT", 2023, 1)
    print(f"\ncex klines: {len(cex):,}")

    # --- the on-chain USDC/USDT basis, aligned onto each pool's blocks -------
    # USDC/USDT pool: token0=USDC, token1=USDT, invert_price=False,
    # so `price` is USDT per USDC. Multiplying an ETH-in-USDT quote by
    # (1 / USDT_per_USDC) converts it to ETH in USDC.
    basis = sus[["block_timestamp", "price"]].rename(columns={"price": "usdt_per_usdc"})
    print(f"USDC/USDT basis: median {float(pd.Series([float(p) for p in sus['price']]).median()):.6f} "
          f"USDT/USDC  (deviation from parity: "
          f"{(float(pd.Series([float(p) for p in sus['price']]).median()) - 1) * 1e4:+.2f} bp)")

    rows = []
    for label, st in (("ETH/USDC 5bp", s05), ("ETH/USDC 30bp", s30)):
        aligned = align_cex_to_blocks(st, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
        assert_causal(aligned)
        ok = aligned["cex_price"].notna()
        a = aligned.loc[ok].copy()

        rows.append(gap_stats(f"{label} vs ETHUSDT (raw)", a["price"], a["cex_price"]))

        # basis-correct: last observed USDC/USDT at or before the block
        a = a.sort_values("block_timestamp")
        merged = pd.merge_asof(
            a, basis.sort_values("block_timestamp"),
            on="block_timestamp", direction="backward",
        )
        m = merged[merged["usdt_per_usdc"].notna()]
        cex_in_usdc = [Decimal(str(c)) / Decimal(str(b))
                       for c, b in zip(m["cex_price"], m["usdt_per_usdc"])]
        rows.append(gap_stats(f"{label} vs ETHUSDT (basis-corrected)", m["price"], cex_in_usdc))

    out = pd.DataFrame(rows)
    print("\n=== price gap, pool vs CEX (basis points) ===")
    print(out.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    r = {x["series"]: x for x in rows}
    b5 = r["ETH/USDC 5bp vs ETHUSDT (basis-corrected)"]["p95_abs_bp"]
    b30 = r["ETH/USDC 30bp vs ETHUSDT (basis-corrected)"]["p95_abs_bp"]
    print(f"\nCHECK 1 — fee-tier band (p95 |gap|, basis-corrected):")
    print(f"  5bp pool  {b5:6.2f} bp")
    print(f"  30bp pool {b30:6.2f} bp")
    print(f"  ratio     {b30 / b5:6.2f}x   -> {'PASS: tighter fee, tighter band' if b30 > b5 else 'FAIL: band does not widen with fee'}")

    d = pd.DataFrame(rows)
    REPO_ROOT.joinpath("outputs", "tables").mkdir(parents=True, exist_ok=True)
    d.to_csv(REPO_ROOT / "outputs" / "tables" / "gap_validation_2023-01.csv", index=False)
    print(f"\nwrote outputs/tables/gap_validation_2023-01.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
