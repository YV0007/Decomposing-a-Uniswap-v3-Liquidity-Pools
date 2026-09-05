"""Bulk data collection for the full sample. Resumable and cached.

Fetched month by month so an interruption costs at most one month's work and a
re-run is a no-op over what already exists. Month boundaries are resolved once
by binary search and cached, since that is ~25 RPC calls each.

Run in the background; Stage 2+ development proceeds on January 2023 meanwhile.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetch.binance_data import load_funding_rates, load_klines_1s
from src.fetch.rpc_client import RPCClient, block_at_or_before, fetch_swaps
from src.utils.config import REPO_ROOT, pools

START = (2023, 1)
END = (2026, 8)          # spec said 2025-12; eight further months now exist
BOUNDARY_CACHE = REPO_ROOT / "data" / "raw" / "month_blocks.json"


def months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_boundaries(client: RPCClient, ms: list[tuple[int, int]]) -> dict[str, int]:
    """Block at or before the first instant of each month, cached to disk."""
    cache = json.loads(BOUNDARY_CACHE.read_text()) if BOUNDARY_CACHE.exists() else {}
    needed = [(y, m) for y, m in ms] + [
        (ms[-1][0] + 1, 1) if ms[-1][1] == 12 else (ms[-1][0], ms[-1][1] + 1)
    ]
    for y, m in needed:
        key = f"{y:04d}-{m:02d}"
        if key in cache:
            continue
        ts = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
        try:
            cache[key] = block_at_or_before(client, ts)
            print(f"  boundary {key} -> block {cache[key]}", flush=True)
        except Exception as exc:
            print(f"  boundary {key} unavailable ({exc}); stopping boundary scan", flush=True)
            break
        BOUNDARY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        BOUNDARY_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return cache


def main() -> int:
    client = RPCClient()
    ms = months(START, END)
    print(f"=== sample: {len(ms)} months, {START} -> {END} ===\n")

    print("--- resolving month block boundaries ---")
    bounds = month_boundaries(client, ms)

    print("\n--- Binance 1s klines + funding ---")
    for y, m in ms:
        for label, fn in (("klines", load_klines_1s), ("funding", load_funding_rates)):
            try:
                fn("ETHUSDT", y, m)
            except Exception as exc:
                print(f"  {label} {y}-{m:02d}: unavailable ({type(exc).__name__})", flush=True)

    print("\n--- Uniswap swaps, core pools ---")
    for spec in pools("core"):
        print(f"\n### {spec.id}")
        for y, m in ms:
            k0 = f"{y:04d}-{m:02d}"
            k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
            if k0 not in bounds or k1 not in bounds:
                print(f"  {k0}: no block boundary, skipping", flush=True)
                continue
            try:
                df = fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1, client=client)
                print(f"  {k0}: {len(df):,} swaps", flush=True)
            except Exception as exc:
                print(f"  {k0}: FAILED {type(exc).__name__} {str(exc)[:80]}", flush=True)

    print("\n=== fetch_all complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
