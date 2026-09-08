"""Fetch and build the derived layer for the extension pools.

Every conclusion so far rests on ETH/USDC — really on 5bp versus 30bp, since the
100bp pool has no viable position size. WBTC/ETH and USDC/USDT were configured
and verified in Stage 1 and never analysed, and they are the cheapest test of
whether any of this generalises.

They also widen the volatility range enormously. ETH/USDC sits near 50%
annualised; BTC/ETH is a cross of two correlated majors and should be lower;
USDC/USDT is a peg and should be near zero. If `sigma^2/8` holds across three
orders of magnitude of variance, that is a far stronger statement than holding
on one asset.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.build.derived import build_pool_month, derived_path, month_bounds
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import RPCClient, fetch_swaps
from src.utils.config import pool

POOLS = ("PAXG_USDC_5bp",)
START, END = (2023, 1), (2026, 7)


def months(a, b):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ms_all = months(START, END)
    bounds = month_bounds()
    client = RPCClient()

    for pid in POOLS:
        spec = pool(pid)
        spec.require_verified()
        # A pool listed after the sample start has nothing before its first
        # month. Fetching those ranges wastes hours and, worse, would write
        # empty months that a later table cannot tell from quiet ones.
        ms = [(y, m) for y, m in ms_all if spec.covers(y, m)]
        print(f"\n=== {pid}: CEX reference {spec.cex_symbol}"
              f"{' (inverted)' if spec.cex_invert else ''} ===", flush=True)

        for y, m in ms:
            try:
                load_klines_1s(spec.cex_symbol, y, m)
            except Exception as exc:
                print(f"  klines {spec.cex_symbol} {y}-{m:02d}: "
                      f"{type(exc).__name__}", flush=True)

        for y, m in ms:
            k0 = f"{y:04d}-{m:02d}"
            k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
            if k0 not in bounds or k1 not in bounds:
                continue
            try:
                fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1, client=client)
            except Exception as exc:
                print(f"  swaps {k0}: FAILED {type(exc).__name__}", flush=True)

        built = failed = 0
        for y, m in ms:
            if derived_path(spec, y, m).exists():
                built += 1
                continue
            try:
                build_pool_month(spec, y, m)
                built += 1
            except Exception as exc:
                failed += 1
                print(f"  derived {y}-{m:02d}: {type(exc).__name__} {str(exc)[:60]}",
                      flush=True)
        print(f"  {pid}: {built} months built, {failed} failed", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
