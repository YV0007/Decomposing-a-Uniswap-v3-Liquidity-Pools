"""Fetch the inputs the delta-hedged variant and the forecast model need.

Perpetual price series and funding for the hedge; DVOL for the implied-vol
feature. Both idempotent and cached.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetch.binance_data import load_funding_rates, load_perp_klines_1m
from src.fetch.deribit import fetch_dvol_month

START, END = (2023, 1), (2026, 8)


def months(a, b):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ms = months(START, END)
    for label, fn in (("perp", load_perp_klines_1m), ("funding", load_funding_rates)):
        print(f"\n=== {label} ===", flush=True)
        for y, m in ms:
            try:
                fn("ETHUSDT", y, m)
            except Exception as exc:
                print(f"  {label} {y}-{m:02d}: {type(exc).__name__} {str(exc)[:60]}", flush=True)

    print("\n=== DVOL ===", flush=True)
    ok = 0
    for y, m in ms:
        try:
            d = fetch_dvol_month("ETH", y, m)
            ok += 1
            print(f"  {y}-{m:02d}: {len(d)} hourly points", flush=True)
        except Exception as exc:
            print(f"  {y}-{m:02d}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
    print(f"\nDVOL: {ok}/{len(ms)} months")
    return 0


if __name__ == "__main__":
    sys.exit(main())
