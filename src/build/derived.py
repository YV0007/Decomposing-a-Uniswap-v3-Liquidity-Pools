"""Derived data layer — one cached table per pool-month.

Everything downstream of Stage 1 wants the same thing: for each block in which a
pool traded, its price, tick, liquidity, the aligned CEX reference, and the
prevailing volatility estimate. Recomputing that from raw logs costs minutes per
pool-month, and the decomposition, the forecast, the strategy backtest and every
robustness sweep would each pay it again.

Building it once and caching it turns the rest of the project into loads.

Two boundary problems are handled here rather than by each caller, because
getting them wrong is silent:

**The volatility window straddles month ends.** A trailing 24h estimate on 1
January needs 31 December's prices. The previous month's CEX tail is loaded and
prepended, then trimmed after the estimator runs, so the first day of every
month has a real estimate rather than a NaN or a short-window artefact.

**Alignment must stay causal across the join.** The aligned CEX price still comes
from the strictly-causal rule in `src.build.align`; prepending history extends
what is available to look *back* at, never forward.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.build.align import AlignmentRule, align_cex_to_blocks, assert_causal
from src.build.pool_state import build_pool_state
from src.fetch.binance_data import load_klines_1s
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.model.volatility import align_to_blocks, realized_variance, to_sampled_prices
from src.utils.config import REPO_ROOT, PoolSpec

PROCESSED = REPO_ROOT / "data" / "processed"
BOUNDS_PATH = REPO_ROOT / "data" / "raw" / "month_blocks.json"

#: Columns persisted as strings to keep exact integers through parquet.
_BIG = ["sqrt_price_x96", "liquidity", "volume0", "volume1"]


def month_bounds() -> dict[str, int]:
    return json.loads(BOUNDS_PATH.read_text())


def prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def derived_path(spec: PoolSpec, year: int, month: int) -> Path:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    return PROCESSED / f"derived_{spec.id}_{year:04d}-{month:02d}.parquet"


def build_pool_month(
    spec: PoolSpec, year: int, month: int, force: bool = False, verbose: bool = True
) -> pd.DataFrame:
    """Build (or load) the derived table for one pool-month."""
    dest = derived_path(spec, year, month)
    if dest.exists() and not force:
        return pd.read_parquet(dest)

    bounds = month_bounds()
    k0 = f"{year:04d}-{month:02d}"
    ky, km = (year + 1, 1) if month == 12 else (year, month + 1)
    k1 = f"{ky:04d}-{km:02d}"
    if k0 not in bounds or k1 not in bounds:
        raise KeyError(f"no block boundary for {k0} or {k1}")

    swaps = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
    if swaps.empty:
        raise ValueError(f"{spec.id} {k0}: no swaps")
    state = build_pool_state(swaps, spec)

    # CEX prices, with the previous month prepended so the trailing volatility
    # window is complete on the first day.
    py, pm = prev_month(year, month)
    frames = []
    try:
        tail = load_klines_1s("ETHUSDT", py, pm)
        frames.append(tail.tail(2 * 24 * 3600))       # 48h is ample for a 24h window
    except Exception:
        pass                                          # first month of the sample
    frames.append(load_klines_1s("ETHUSDT", year, month))
    cex = pd.concat(frames, ignore_index=True).sort_values("second")
    cex = cex.drop_duplicates(subset="second", keep="last").reset_index(drop=True)

    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert_causal(aligned)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)
    if aligned.empty:
        raise ValueError(f"{spec.id} {k0}: no blocks matched a CEX price")

    rv = realized_variance(to_sampled_prices(cex, sample_minutes=5))
    aligned["rv_annualised"] = align_to_blocks(rv, aligned["block_timestamp"]).to_numpy()

    out = aligned[
        ["block_number", "block_timestamp", "sqrt_price_x96", "tick", "liquidity",
         "price", "cex_price", "cex_second", "staleness_seconds", "rv_annualised",
         "volume0", "volume1", "n_swaps"]
    ].copy()
    for c in _BIG:
        out[c] = out[c].map(lambda v: str(int(v)))
    out["price"] = out["price"].map(str)
    out["cex_price"] = out["cex_price"].map(str)
    out["pool"] = spec.id
    out["year"], out["month"] = year, month
    out.to_parquet(dest, index=False)

    if verbose:
        cov = out["rv_annualised"].notna().mean()
        print(f"  {spec.id} {k0}: {len(out):,} blocks, vol coverage {cov:.1%}", flush=True)
    return out


def load_derived(
    spec: PoolSpec, months: list[tuple[int, int]], to_decimal: bool = True
) -> pd.DataFrame:
    """Load several derived pool-months as one frame, restoring exact types."""
    frames = []
    for y, m in months:
        p = derived_path(spec, y, m)
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        raise FileNotFoundError(f"no derived months found for {spec.id}")

    df = pd.concat(frames, ignore_index=True).sort_values("block_number").reset_index(drop=True)
    for c in _BIG:
        df[c] = pd.Series([int(v) for v in df[c]], dtype=object)
    if to_decimal:
        df["price"] = pd.Series([Decimal(v) for v in df["price"]], dtype=object)
        df["cex_price"] = pd.Series([Decimal(v) for v in df["cex_price"]], dtype=object)
    return df


def available_months(spec: PoolSpec) -> list[tuple[int, int]]:
    """Which pool-months have been built."""
    out = []
    for p in sorted(PROCESSED.glob(f"derived_{spec.id}_*.parquet")):
        y, m = p.stem.rsplit("_", 1)[1].split("-")
        out.append((int(y), int(m)))
    return out
