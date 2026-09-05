"""Stage 3 — LVR, empirical and analytical, and the H3 comparison.

Gate: LVR positive on net, plausible in magnitude, and the same order of
magnitude as the closed form. A failure means stop and diagnose.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks, assert_causal
from src.build.lvr import compute_lvr, gate_lvr_sanity
from src.build.pool_state import build_pool_state
from src.build.position import open_position, simulate
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.model.volatility import align_to_blocks, realized_variance, to_sampled_prices
from src.utils.config import REPO_ROOT, pool

POOL_ID, B0, B1 = "ETH_USDC_30bp", 16308189, 16530247
NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")


def main() -> int:
    spec = pool(POOL_ID)
    spec.require_verified()

    swaps = load_big_ints(fetch_swaps(spec.address, B0, B1, client=RPCClient()))
    state = build_pool_state(swaps, spec)
    cex = load_klines_1s("ETHUSDT", 2023, 1)

    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert_causal(aligned)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)

    px = to_sampled_prices(cex, sample_minutes=5)
    rv = realized_variance(px, sample_minutes=5, window_hours=24)
    vol = align_to_blocks(rv, aligned["block_timestamp"])
    print(f"blocks {len(aligned):,}   5-min bars {len(px):,}   "
          f"vol coverage {vol.notna().mean():.1%}")
    sig = vol.dropna().pow(0.5)
    print(f"annualised sigma: median {sig.median():.1%}  "
          f"p5 {sig.quantile(.05):.1%}  p95 {sig.quantile(.95):.1%}\n")

    entry = aligned.iloc[0]
    pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                        Decimal(str(entry.price)), NOTIONAL, HALF_WIDTH)
    sim = simulate(state, pos, spec)
    print(f"position: ${NOTIONAL:,} at +/-{HALF_WIDTH:.0%}, ticks "
          f"[{pos.tick_lower}, {pos.tick_upper}], in range {sim.in_range.mean():.1%}\n")

    res = compute_lvr(aligned, pos, spec, vol)

    print(f"=== LVR over {float(res.days):.1f} days, mean position value "
          f"${float(res.mean_position_value):,.0f} ===\n")
    rows = [
        ("empirical, pool path", res.annualised_pool_path,
         "value actually lost as the pool moved, marked at the CEX price"),
        ("empirical, CEX path", res.annualised_cex_path,
         "loss under perfect arbitrage every block — what sigma^2/8 predicts"),
        ("analytical, position-aware", res.annualised_analytical,
         "(sigma^2/2) S^2 |dn/dS| on this position's own amount function"),
        ("analytical, naive sigma^2 V/8", res.annualised_naive_v2,
         "textbook full-range form applied to a concentrated position"),
    ]
    print(f"{'measure':32s} {'annualised':>12s}   note")
    print("-" * 108)
    for name, val, note in rows:
        print(f"{name:32s} {float(val):11.2%}   {note}")

    a, n = res.annualised_analytical, res.annualised_naive_v2
    print(f"\nconcentration effect: position-aware / naive = {float(a / n):.2f}x")
    print(f"  -> applying the full-range form to this +/-10% position understates "
          f"LVR by {float(1 - n / a):.0%}")

    c, p = res.annualised_cex_path, res.annualised_pool_path
    print(f"\nfrictional wedge: pool path / CEX path = {float(p / c):.2f}")
    print(f"  -> fees and gas mean the pool is not corrected on every block, so the")
    print(f"     LP loses {float(1 - p / c):.0%} less than perfect arbitrage would take")

    print("\n--- STAGE 3 GATE ---")
    g = gate_lvr_sanity(res)
    for k, v in g["checks"].items():
        print(f"  {k:28s} {'PASS' if v else 'FAIL'}")
    print(f"  -> {'PASS' if g['passed'] else 'FAIL — stop and diagnose'}")

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "pool": POOL_ID, "days": float(res.days),
        "mean_value_usd": float(res.mean_position_value),
        "lvr_pool_path": float(res.annualised_pool_path),
        "lvr_cex_path": float(res.annualised_cex_path),
        "lvr_analytical": float(res.annualised_analytical),
        "lvr_naive_v2": float(res.annualised_naive_v2),
        "gate_passed": g["passed"],
    }]).to_csv(out / "stage3_lvr_2023-01.csv", index=False)
    print(f"\nwrote outputs/tables/stage3_lvr_2023-01.csv")
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
