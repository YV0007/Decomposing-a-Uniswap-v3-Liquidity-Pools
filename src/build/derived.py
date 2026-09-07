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

Two prices per pool, not one
----------------------------
The **reference** is whatever Binance symbol is directly comparable to the
pool's own quote — ETHUSDT for ETH/USDC, ETHBTC inverted for WBTC/ETH, USDCUSDT
for USDC/USDT. It is what LVR is measured against.

The **numeraire** is the USD price of token1, needed to turn token amounts into
dollars so that gas and notional mean anything. For ETH/USDC the two coincide;
for WBTC/ETH they do not, and conflating them would price a BTC position off a
BTC/ETH exchange rate.
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


def daily_lvr_table() -> Path:
    """The daily LVR table to read: the five-pool one if it has been built.

    `cross_section_daily.parquet` is a superset of `h3_daily.parquet` — same
    columns, three more pools. Scripts that restrict to their own pool set get
    identical results from either, so preferring the superset means a
    reproduction run regenerates what the deck quotes instead of the
    three-pool numbers it superseded.
    """
    xs = PROCESSED / "cross_section_daily.parquet"
    return xs if xs.exists() else PROCESSED / "h3_daily.parquet"


def weekly_panel_table() -> Path:
    """The weekly panel to read: the five-pool one if it has been built."""
    a = PROCESSED / "weekly_panel_all.parquet"
    return a if a.exists() else PROCESSED / "weekly_panel.parquet"


def month_bounds() -> dict[str, int]:
    return json.loads(BOUNDS_PATH.read_text())


def reference_frame(spec: PoolSpec, year: int, month: int, with_tail: bool = True):
    """The CEX series comparable to this pool's own price quote.

    Inverted where the exchange quotes the pair the other way round: the pool's
    WBTC/WETH price is ETH per BTC while Binance ETHBTC is BTC per ETH.
    """
    frames = []
    if with_tail:
        py, pm = prev_month(year, month)
        try:
            frames.append(load_klines_1s(spec.cex_symbol, py, pm).tail(2 * 24 * 3600))
        except Exception:
            pass
    frames.append(load_klines_1s(spec.cex_symbol, year, month))
    cex = pd.concat(frames, ignore_index=True).sort_values("second")
    cex = cex.drop_duplicates(subset="second", keep="last").reset_index(drop=True)
    if spec.cex_invert:
        for col in ("close", "high", "low"):
            if col in cex.columns:
                cex[col] = (1.0 / cex[col].astype(float)).map(lambda v: f"{v:.12f}")
    return cex


def numeraire_frame(spec: PoolSpec, year: int, month: int):
    """USD price of token1, so token amounts can be turned into dollars.

    WETH is priced from ETHUSDT. A stablecoin token1 is taken as $1 — an
    assumption, but one whose error is basis points and which only enters the
    dollar *scale* of a stable/stable pool, never its returns.

    The previous month's tail is prepended, exactly as for the reference series.
    Without it the first blocks of a month have nothing to look *back* at and
    the numeraire is null there — which surfaced as a `decimal.InvalidOperation`
    two months into the WBTC/ETH build, from a single NaN row. Back-filling
    instead would be lookahead.
    """
    t1 = spec.token1.symbol
    if t1 in {"USDC", "USDT", "DAI"}:
        return None                      # $1; handled by the caller
    if t1 != "WETH":
        raise NotImplementedError(f"no USD numeraire configured for {t1}")

    frames = []
    py, pm = prev_month(year, month)
    try:
        frames.append(load_klines_1s("ETHUSDT", py, pm).tail(2 * 24 * 3600))
    except Exception:
        pass
    frames.append(load_klines_1s("ETHUSDT", year, month))
    out = pd.concat(frames, ignore_index=True).sort_values("second")
    return out.drop_duplicates(subset="second", keep="last").reset_index(drop=True)


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
    cex = reference_frame(spec, year, month)

    aligned = align_cex_to_blocks(state, cex, AlignmentRule.LAST_TRADE_AT_OR_BEFORE_BLOCK_TS)
    assert_causal(aligned)
    aligned = aligned[aligned["cex_price"].notna()].reset_index(drop=True)
    if aligned.empty:
        raise ValueError(f"{spec.id} {k0}: no blocks matched a CEX price")

    rv = realized_variance(to_sampled_prices(cex, sample_minutes=5))
    aligned["rv_annualised"] = align_to_blocks(rv, aligned["block_timestamp"]).to_numpy()

    # Numeraire: USD price of token1, aligned by the same causal rule.
    num = numeraire_frame(spec, year, month)
    if num is None:
        aligned["numeraire_usd"] = 1.0
    else:
        n = num.rename(columns={"second": "cex_second_n", "close": "numeraire_usd"})
        left = aligned[["block_timestamp"]].copy()
        left["_key"] = left["block_timestamp"].astype("int64") - 1
        merged = pd.merge_asof(
            left.sort_values("_key"),
            n[["cex_second_n", "numeraire_usd"]].sort_values("cex_second_n"),
            left_on="_key", right_on="cex_second_n", direction="backward",
        )
        vals = merged["numeraire_usd"].astype(float)
        # Forward-fill only: a gap in the kline series is covered by the last
        # observed price, never by a later one.
        vals = vals.ffill()
        if vals.isna().any():
            raise ValueError(
                f"{spec.id} {k0}: numeraire null for {int(vals.isna().sum())} blocks "
                f"even after prepending the previous month — no price exists before "
                f"them, so those blocks cannot be valued in USD."
            )
        aligned["numeraire_usd"] = vals.to_numpy()

    out = aligned[
        ["block_number", "block_timestamp", "sqrt_price_x96", "tick", "liquidity",
         "price", "cex_price", "cex_second", "staleness_seconds", "rv_annualised",
         "numeraire_usd", "volume0", "volume1", "n_swaps"]
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
            f = pd.read_parquet(p)
            f.attrs["invert_price"] = spec.invert_price
            frames.append(f)
    if not frames:
        raise FileNotFoundError(f"no derived months found for {spec.id}")

    df = pd.concat(frames, ignore_index=True).sort_values("block_number").reset_index(drop=True)
    if "numeraire_usd" not in df.columns:
        # Files built before the numeraire column existed. For a pool with a
        # stable leg it is recoverable exactly: the inverted pools quote token1
        # in USD directly, and a stable token1 is $1.
        spec_inv = df.attrs.get("invert_price")
        df["numeraire_usd"] = (df["price"].astype(float) if spec_inv is not False
                               else 1.0)
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
