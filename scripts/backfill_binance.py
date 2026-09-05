"""Backfill the Binance months a transient network failure skipped.

Separate from `fetch_all.py` so it can run alongside the swap fetch without
restarting it. Idempotent: months already cached are skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetch.binance_data import load_funding_rates, load_klines_1s

START, END = (2023, 1), (2026, 8)


def months(a, b):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ok = fail = 0
    for y, m in months(START, END):
        for label, fn in (("klines", load_klines_1s), ("funding", load_funding_rates)):
            try:
                fn("ETHUSDT", y, m)
                ok += 1
            except Exception as exc:
                print(f"  {label} {y}-{m:02d}: {type(exc).__name__} {str(exc)[:70]}", flush=True)
                fail += 1
    print(f"\nbackfill done: {ok} available, {fail} unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
