"""Stage 2 — LP position reconstruction and fee accrual, with the gate.

Gate: replayed fee accrual (approach B, from swap events) must sit within 2% of
the contract's own accounting (approach C, `feeGrowthInside` read at the entry
and exit blocks). C is the source the subgraph itself derives from, so this
validates against the origin rather than a copy.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.fees import (accrue_fees_approach_b, fees_exact, fees_to_usd,
                            gate_fee_accrual)
from src.build.pool_state import build_pool_state
from src.build.position import open_position, simulate
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

POOL_ID, B0, B1 = "ETH_USDC_30bp", 16308189, 16530247
NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")


def main() -> int:
    client = RPCClient()
    spec = pool(POOL_ID)
    spec.require_verified()

    swaps = load_big_ints(fetch_swaps(spec.address, B0, B1, client=client))
    state = build_pool_state(swaps, spec)

    entry = state.iloc[0]
    pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                        Decimal(str(entry.price)), NOTIONAL, HALF_WIDTH)
    print(f"=== position: {POOL_ID}, ${NOTIONAL:,} at +/-{HALF_WIDTH:.0%} ===")
    print(f"  entry block {pos.entry_block}  price ${float(entry.price):,.2f}")
    print(f"  ticks [{pos.tick_lower}, {pos.tick_upper}]  liquidity {pos.liquidity:,}\n")

    sim = simulate(state, pos, spec)
    print(f"  blocks simulated : {len(sim):,}")
    print(f"  share in range   : {sim.in_range.mean():.1%}")
    print(f"  value entry/exit : ${float(sim.value_usd.iloc[0]):,.2f} -> "
          f"${float(sim.value_usd.iloc[-1]):,.2f}\n")

    # --- approach B: replay from swap events -------------------------------- #
    after_entry = swaps[swaps["block_number"] > int(entry.block_number)]
    replay = accrue_fees_approach_b(after_entry, pos, spec, entry_tick=int(entry.tick),
                                    deposited=False)  # match feeGrowthInside
    rep0, rep1 = int(replay.fee0.sum()), int(replay.fee1.sum())

    # --- approach C: the contract's own accounting -------------------------- #
    end = state.iloc[-1]
    exa0, exa1 = fees_exact(
        client, spec, pos,
        int(entry.block_number), int(entry.tick),
        int(end.block_number), int(end.tick),
    )

    print("--- GATE: replayed accrual vs the contract's feeGrowthInside ---")
    g = gate_fee_accrual((rep0, rep1), (exa0, exa1))
    for name, dec, sym in (("token0", spec.token0.decimals, spec.token0.symbol),
                           ("token1", spec.token1.decimals, spec.token1.symbol)):
        rel = g[f"{name}_rel_error"]
        print(f"  {sym:5s} replay {g[f'{name}_replay'] / 10**dec:>14,.6f}   "
              f"exact {g[f'{name}_exact'] / 10**dec:>14,.6f}   "
              f"rel error {('n/a' if rel is None else f'{rel:+.4%}')}")
    print(f"  -> {'PASS' if g['passed'] else 'FAIL'} (tolerance 2%)\n")

    exit_price = Decimal(str(end.price))
    usd_replay = fees_to_usd(rep0, rep1, spec, exit_price)
    usd_exact = fees_to_usd(exa0, exa1, spec, exit_price)
    days = (int(end.block_timestamp) - int(entry.block_timestamp)) / 86400
    print(f"--- fee income on ${NOTIONAL:,} over {days:.1f} days ---")
    print(f"  replay : ${float(usd_replay):,.2f}   ({float(usd_replay) / float(NOTIONAL) * 365 / days:.2%} annualised)")
    print(f"  exact  : ${float(usd_exact):,.2f}   ({float(usd_exact) / float(NOTIONAL) * 365 / days:.2%} annualised)")
    print(f"\n  NB: fees stopped accruing when the position left range on day "
          f"{(replay[replay.in_range].block_timestamp.max() - int(entry.block_timestamp)) / 86400:.1f}.")

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "pool": POOL_ID, "notional_usd": float(NOTIONAL), "half_width": float(HALF_WIDTH),
        "tick_lower": pos.tick_lower, "tick_upper": pos.tick_upper,
        "share_in_range": float(sim.in_range.mean()),
        "fees_usd_replay": float(usd_replay), "fees_usd_exact": float(usd_exact),
        "rel_error_token0": g["token0_rel_error"], "rel_error_token1": g["token1_rel_error"],
        "gate_passed": g["passed"],
    }]).to_csv(out / "stage2_fee_gate_2023-01.csv", index=False)

    print(f"\n=== STAGE 2 GATE: {'PASS' if g['passed'] else 'FAIL — stop and diagnose'} ===")
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
