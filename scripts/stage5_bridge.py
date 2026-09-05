"""The advertised-APR-to-net bridge. Output 1, in its honest form.

Shows *why* the advertised number overstates what an LP earns, separating the
cost of using a concentrated range from the adverse-selection costs that are the
paper's actual subject.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.decomposition import advertised_to_net_bridge
from src.build.pipeline import run_pool_period
from src.build.pool_state import build_pool_state
from src.fetch.binance_data import load_klines_1s
from src.fetch.pool_metrics import pool_summary
from src.fetch.rpc_client import RPCClient, fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pools

B0, B1 = 16308189, 16530247
NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")


def main() -> int:
    client = RPCClient()
    cex = load_klines_1s("ETHUSDT", 2023, 1)
    rows = []

    for spec in pools("core"):
        swaps = load_big_ints(fetch_swaps(spec.address, B0, B1, client=client))
        st = build_pool_state(swaps, spec)
        seconds = int(st.iloc[-1].block_timestamp - st.iloc[0].block_timestamp)
        summ = pool_summary(
            client, spec, swaps, int(st.iloc[0].block_number), int(st.iloc[-1].block_number),
            Decimal(str(st.iloc[0].price)), Decimal(str(st.iloc[-1].price)), seconds,
        )
        row, aux = run_pool_period(spec, B0, B1, cex, NOTIONAL, HALF_WIDTH, client, verbose=False)
        b = advertised_to_net_bridge(
            summ["advertised_apr"], row.fees, row.lvr, row.mev, row.gas, row.share_in_range
        )
        rows.append({"pool": spec.id, "fee_tier_bps": spec.fee_tier_bps,
                     "tvl_usd": float(summ["tvl_mean_usd"]),
                     "share_in_range": float(row.share_in_range),
                     **{k: float(v) for k, v in b.items()}})

    t = pd.DataFrame(rows)
    print("\n=== Advertised APR -> realised net, ETH/USDC, January 2023 ===")
    print("    $100k position, +/-10%, never re-centred, unhedged\n")
    cols = ["pool", "advertised_apr", "range_management_cost", "expected_if_proportional",
            "concentration_effect", "gross_fees_realised", "lvr", "mev", "gas", "net"]
    show = t[cols].copy()
    for c in cols[1:]:
        show[c] = show[c].map(lambda v: f"{v:+8.2%}")
    print(show.to_string(index=False))

    print("\n--- what drives the gap between advertised and realised? ---")
    for _, r in t.iterrows():
        print(f"  {r['pool']:16s} advertised {r['advertised_apr']:6.2%} -> net {r['net']:+6.2%}"
              f"   range management {r['share_of_gap_from_range']:5.0%} of the gap,"
              f"   LVR+MEV+gas {r['share_of_gap_from_costs']:5.0%}")

    print("\nRead this carefully. The advertised figure divides pool fee revenue by TOTAL")
    print("TVL, as though every dollar earned every fee. Most of the gap to a realised")
    print("position is the cost of holding a concentrated range that spends time out of")
    print("range — a cost of using v3, not adverse selection. LVR is the smaller share")
    print("here, and saying otherwise would overstate the paper's own thesis.")

    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "advertised_bridge_2023-01.csv", index=False)
    print(f"\nwrote outputs/tables/advertised_bridge_2023-01.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
