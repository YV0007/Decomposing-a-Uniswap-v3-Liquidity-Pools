"""Stage 5 — the decomposition table across the core pools.

ETH/USDC at 5bp, 30bp and 100bp over the same month: same asset, same
volatility, different fee. The H4 natural experiment.

MEV is not yet attributed, so the net column is an upper bound. Stated on the
table rather than left for the reader to infer.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.decomposition import decomposition_table, gate_signs_and_magnitudes
from src.build.pipeline import run_pool_period
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient
from src.utils.config import REPO_ROOT, pools

B0, B1 = 16308189, 16530247
NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")


def main() -> int:
    client = RPCClient()
    cex = load_klines_1s("ETHUSDT", 2023, 1)
    rows, extras = [], {}

    for spec in pools("core"):
        try:
            row, aux = run_pool_period(spec, B0, B1, cex, NOTIONAL, HALF_WIDTH, client)
            rows.append(row)
            extras[spec.id] = aux
            print(f"    fees {float(row.fees):.2%}  lvr {float(row.lvr):.2%}  "
                  f"gas {float(row.gas):.3%}  -> net {float(row.net):+.2%}", flush=True)
        except Exception as exc:
            print(f"  {spec.id}: FAILED {type(exc).__name__}: {exc}", flush=True)

    table = decomposition_table(rows)
    # Both LVR measures side by side. `cex_path` assumes perfect arbitrage every
    # block, so it depends only on the external price path and the position's
    # shape — it is fee-tier-blind BY CONSTRUCTION. H4's mechanism lives in
    # `pool_path`, which reflects what the pool price actually did and therefore
    # feels the width of the no-arbitrage band the fee sets.
    table["lvr_cex_path"] = [-float(extras[r.pool_id]["lvr"].annualised_cex_path) for r in rows]
    table["lvr_pool_path"] = [-float(extras[r.pool_id]["lvr"].annualised_pool_path) for r in rows]
    table["lvr_analytical"] = [-float(extras[r.pool_id]["lvr"].annualised_analytical) for r in rows]
    table["net_pool_path"] = table["fees"] + table["lvr_pool_path"] + table["gas"]
    print("\n=== Output 1 (preview): ETH/USDC, January 2023, $100k at +/-10% ===\n")
    cols = ["pool", "fee_tier_bps", "share_in_range", "fees",
            "lvr_cex_path", "lvr_pool_path", "lvr_analytical", "gas", "net", "net_pool_path"]
    show = table[cols].copy()
    for c in cols[2:]:
        show[c] = show[c].map(lambda v: f"{v:+.2%}")
    print(show.to_string(index=False))
    print("\nshare_in_range is TIME-weighted, so it is comparable across pools that")
    print("trade at very different frequencies.")
    print("lvr_cex_path assumes perfect arbitrage every block and is fee-tier-blind by")
    print("construction; lvr_pool_path measures what the pool price actually did, so it")
    print("is where the H4 fee-band mechanism shows up.")
    print("MEV not yet attributed, so both net columns are upper bounds.")

    g = gate_signs_and_magnitudes(table)
    print("\n--- sign and magnitude checks ---")
    for k, v in g["checks"].items():
        print(f"  {k:24s} {'PASS' if v else 'FAIL'}")

    print("\n--- fee gate per pool (replay vs contract feeGrowthInside) ---")
    for pid, aux in extras.items():
        e = aux["fee_check"]["rel_error"]
        print(f"  {pid:16s} {'n/a' if e is None else f'{e:+.3%}'}")

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "decomposition_2023-01.csv", index=False)
    print(f"\nwrote outputs/tables/decomposition_2023-01.csv")
    return 0
if __name__ == "__main__":
    sys.exit(main())
