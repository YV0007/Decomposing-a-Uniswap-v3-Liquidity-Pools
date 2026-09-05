"""Stage 8 — optimal range width: closed form against the empirical sweep.

The theory predicts an interior optimum with a closed form. This sweeps real
range widths on real data, with re-centring, and asks whether the empirical
optimum lands where the derivation says it should.
"""

from __future__ import annotations

import math
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks
from src.build.pool_state import build_pool_state
from src.build.recentre import simulate_recentred
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.model.volatility import align_to_blocks, realized_variance, to_sampled_prices
from src.theory.range_width import (calibrate_fee_coefficient, kappa, net_rate,
                                    optimal_half_width, tick_spacing_half_width)
from src.utils.config import REPO_ROOT, pool

POOL_ID, B0, B1 = "ETH_USDC_30bp", 16308189, 16530247
NOTIONAL = Decimal("100000")
WIDTHS = ["0.01", "0.02", "0.03", "0.05", "0.075", "0.10", "0.15", "0.25", "0.40"]
GAS_RECENTRE = Decimal("22.39")     # burn + collect + mint, measured
GAS_ENTRY_EXIT = Decimal("22.39")


def main() -> int:
    client = RPCClient()
    spec = pool(POOL_ID)
    swaps = load_big_ints(fetch_swaps(spec.address, B0, B1, client=client))
    state = build_pool_state(swaps, spec)
    cex = load_klines_1s("ETHUSDT", 2023, 1)
    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)
    vol = align_to_blocks(realized_variance(to_sampled_prices(cex)), aligned["block_timestamp"])

    print(f"=== empirical sweep: {POOL_ID}, January 2023, ${NOTIONAL:,}, re-centred on exit ===\n")
    rows = []
    for w in WIDTHS:
        r = simulate_recentred(aligned, swaps, spec, NOTIONAL, Decimal(w), vol,
                               GAS_RECENTRE, GAS_ENTRY_EXIT)
        rows.append({
            "half_width": float(w),
            "realised_delta": r.realised_half_width_log,
            "n_recentres": r.n_recentres,
            "share_in_range": float(r.share_in_range),
            "fees": float(r.fees),
            "lvr": float(r.lvr_cex_path),
            "gas": float(r.gas),
            "net": float(r.net),
        })
        print(f"  +/-{float(w):5.1%}  delta={r.realised_half_width_log:.4f}  "
              f"recentres={r.n_recentres:3d}  in range={float(r.share_in_range):5.1%}  "
              f"fees={float(r.fees):+7.2%}  lvr={float(r.lvr_cex_path):+7.2%}  "
              f"gas={float(r.gas):+7.2%}  net={float(r.net):+7.2%}", flush=True)

    t = pd.DataFrame(rows)
    best = t.loc[t["net"].idxmax()]
    print(f"\nempirical optimum: +/-{best['half_width']:.1%} "
          f"(delta = {best['realised_delta']:.4f}), net {best['net']:+.2%}")

    # --- theory, calibrated on the sweep itself --------------------------- #
    ref = t.iloc[(t["half_width"] - 0.10).abs().idxmin()]
    in_range_fee_rate = ref["fees"] / max(1e-9, ref["share_in_range"])
    F = calibrate_fee_coefficient(in_range_fee_rate, ref["realised_delta"])
    sig2 = float(pd.Series(vol).dropna().mean())
    sigma = math.sqrt(sig2)
    A = float(GAS_RECENTRE / NOTIONAL)

    sol = optimal_half_width(F, sigma, A, tick_spacing=spec.tick_spacing)
    print(f"\n=== closed form, calibrated from the +/-{ref['half_width']:.0%} row ===")
    print(f"  sigma = {sigma:.3f}   F = {F:.5f}   sigma^2/4 = {sigma**2 / 4:.5f}   A = {A:.2e}")
    print(f"  kappa = {sol.kappa:+.5f}  ->  {'profitable at some width' if sol.profitable else 'unprofitable at every width'}")
    if sol.profitable:
        d = sol.realisable_half_width
        print(f"  predicted delta* = {d:.4f}  (+/-{math.exp(d) - 1:.2%}), binding: {sol.binding_constraint}")
        print(f"  tick-grid floor  = {tick_spacing_half_width(spec.tick_spacing):.4f}")
        print(f"\n  predicted +/-{math.exp(d) - 1:.1%}   vs   empirical +/-{best['half_width']:.1%}")
    print(f"  {sol.note}")

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "range_width_sweep_2023-01.csv", index=False)
    print(f"\nwrote outputs/tables/range_width_sweep_2023-01.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
