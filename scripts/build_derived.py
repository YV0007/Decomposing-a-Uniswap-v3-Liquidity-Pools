"""Precompute the derived layer for every pool-month. Resumable and idempotent."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.build.derived import build_pool_month, derived_path, month_bounds
from src.utils.config import pools

START, END = (2023, 1), (2026, 7)      # Aug 2026 CEX klines not yet published


def months(a, b):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ms = months(START, END)
    todo = [(s, y, m) for s in pools("core") for y, m in ms
            if not derived_path(s, y, m).exists()]
    print(f"{len(todo)} pool-months to build "
          f"({len(pools('core')) * len(ms) - len(todo)} already cached)\n", flush=True)

    ok = fail = 0
    for spec, y, m in todo:
        try:
            build_pool_month(spec, y, m)
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"  {spec.id} {y}-{m:02d}: FAILED {type(exc).__name__} {str(exc)[:70]}",
                  flush=True)
    print(f"\nbuilt {ok}, failed {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
