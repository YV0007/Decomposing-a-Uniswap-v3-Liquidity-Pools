"""Retry any pool-month whose swap fetch failed. Idempotent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetch.rpc_client import RPCClient, fetch_swaps
from src.utils.config import REPO_ROOT, pools

BOUNDS = json.loads((REPO_ROOT / "data" / "raw" / "month_blocks.json").read_text())


def main() -> int:
    client = RPCClient()
    keys = sorted(BOUNDS)
    missing = []
    for spec in pools("core"):
        for k0, k1 in zip(keys[:-1], keys[1:]):
            b0, b1 = BOUNDS[k0], BOUNDS[k1] - 1
            cache = (REPO_ROOT / "data" / "raw" / "swaps" /
                     f"{spec.address}_{b0}_{b1}_v3.parquet")
            if not cache.exists():
                missing.append((spec, k0, b0, b1))

    print(f"{len(missing)} pool-months missing\n")
    still = 0
    for spec, k0, b0, b1 in missing:
        try:
            df = fetch_swaps(spec.address, b0, b1, client=client)
            print(f"  {spec.id} {k0}: {len(df):,} swaps", flush=True)
        except Exception as exc:
            still += 1
            print(f"  {spec.id} {k0}: STILL FAILING {type(exc).__name__}", flush=True)
    print(f"\n{len(missing) - still} recovered, {still} still failing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
