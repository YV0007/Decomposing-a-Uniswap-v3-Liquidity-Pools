"""Robustness — does the block/CEX alignment rule change LVR? (open question 3)

Closed on one month in Stage 1.5; this re-tests it across the full sample, since
a rule that barely mattered in a single calm month could matter over 43.

Three rules:
- last trade at or before the block timestamp (baseline, strictly causal)
- one beacon slot earlier (staler, still causal — tests sensitivity to
  proposer-set timestamps, which can drift by seconds)
- midpoint interpolation (**uses lookahead by construction**; included only to
  bound how much the answer could move, and excluded from every headline)
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks
from src.build.derived import available_months, month_bounds
from src.build.lvr import lvr_from_cex_path
from src.build.pool_state import build_pool_state
from src.build.position import open_position
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")
#: Every third month, so the sweep covers all four years without re-aligning
#: 8.6m swaps three times over.
STRIDE = 3


def month_lvr(spec, y, m, bounds, rule) -> dict | None:
    k0 = f"{y:04d}-{m:02d}"
    k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
    if k0 not in bounds or k1 not in bounds:
        return None
    sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
    st = build_pool_state(sw, spec)
    if len(st) < 50:
        return None
    cex = load_klines_1s("ETHUSDT", y, m)
    aligned = align_cex_to_blocks(st, cex, rule)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)
    if aligned.empty:
        return None

    e = aligned.iloc[0]
    pos = open_position(spec, int(e.block_number), int(e.sqrt_price_x96),
                        Decimal(str(e.price)), Decimal("100000"), Decimal("0.10"))
    total = Decimal(0)
    prev = None
    for c in aligned["cex_price"]:
        cur = Decimal(str(c))
        if prev is not None:
            total += lvr_from_cex_path(pos, spec, prev, cur)
        prev = cur
    return {"pool": spec.id, "month": k0, "rule": rule.value,
            "lvr_usd": float(total), "n_blocks": len(aligned),
            "median_staleness_s": float(aligned["staleness_seconds"].median())}


def main() -> int:
    bounds = month_bounds()
    rows = []
    for pid in POOLS:
        spec = pool(pid)
        months = available_months(spec)[::STRIDE]
        for y, m in months:
            for rule in AlignmentRule:
                try:
                    r = month_lvr(spec, y, m, bounds, rule)
                    if r:
                        rows.append(r)
                except Exception as exc:
                    print(f"  {pid} {y}-{m:02d} {rule.value}: {type(exc).__name__}",
                          flush=True)
            print(f"  {pid} {y}-{m:02d} done", flush=True)

    t = pd.DataFrame(rows)
    piv = t.pivot_table(index=["pool", "month"], columns="rule", values="lvr_usd")
    base = AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS.value
    print(f"\n=== LVR by alignment rule, {t.month.nunique()} months, "
          f"{t.pool.nunique()} pools ===\n")
    summary = []
    for rule in [r.value for r in AlignmentRule]:
        if rule not in piv.columns:
            continue
        ratio = (piv[rule] / piv[base]).dropna()
        summary.append({"rule": rule, "n": len(ratio), "mean_ratio": ratio.mean(),
                        "p5": ratio.quantile(.05), "p95": ratio.quantile(.95),
                        "max_abs_dev": (ratio - 1).abs().max(),
                        "lookahead": rule == AlignmentRule.MIDPOINT_INTERPOLATION.value})
    s = pd.DataFrame(summary)
    print(s.to_string(index=False, float_format=lambda v: f"{v:9.4f}"))
    print(f"\n  ratios are relative to the baseline rule; 1.0 means no change")
    worst = s[~s.lookahead]["max_abs_dev"].max()
    print(f"\n  largest deviation among CAUSAL rules: {worst:.2%}")
    print(f"  -> {'the rule matters and earns a slide' if worst > 0.05 else 'the rule does not matter; a sentence suffices'}")

    t.to_csv(REPO_ROOT / "outputs" / "tables" / "robustness_alignment.csv", index=False)
    s.to_csv(REPO_ROOT / "outputs" / "tables" / "robustness_alignment_summary.csv", index=False)
    print(f"\nwrote robustness_alignment.csv and robustness_alignment_summary.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
