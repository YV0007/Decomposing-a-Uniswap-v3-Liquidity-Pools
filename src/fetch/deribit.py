"""Deribit public API — the implied-volatility feature.

DVOL is Deribit's 30-day forward implied volatility index for ETH. It enters the
forecast model as `implied_vol`, the one feature that is genuinely forward
looking rather than a transformation of realised history — which is what makes
it worth having alongside realised volatility.

Public endpoint, no key, no rate limit worth managing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE = "https://www.deribit.com/api/v2/public"
MAX_ATTEMPTS = 4


def _cache_dir() -> Path:
    from src.utils.config import REPO_ROOT

    d = REPO_ROOT / "data" / "raw" / "deribit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str) -> dict:
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(2 * (2**attempt))
    raise RuntimeError(f"deribit request failed: {url}") from last


def fetch_dvol_month(currency: str, year: int, month: int, force: bool = False) -> pd.DataFrame:
    """One month of hourly DVOL, cached.

    Returned as OHLC per hour. The `close` is used downstream; the range is kept
    because intraday implied-vol range is itself a candidate feature.
    """
    cache = _cache_dir() / f"dvol-{currency}-{year:04d}-{month:02d}.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    url = (
        f"{BASE}/get_volatility_index_data?currency={currency}"
        f"&start_timestamp={int(start.timestamp() * 1000)}"
        f"&end_timestamp={int(end.timestamp() * 1000)}&resolution=3600"
    )
    rows = _get(url)["result"]["data"]
    if not rows:
        raise ValueError(f"no DVOL data for {currency} {year}-{month:02d}")

    df = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close"])
    df["hour"] = (df["timestamp_ms"] // 1000).astype("int64")
    df = df[["hour", "open", "high", "low", "close"]].sort_values("hour").reset_index(drop=True)
    df.to_parquet(cache, index=False)
    return df


def load_dvol(currency: str, months: list[tuple[int, int]]) -> pd.DataFrame:
    """Concatenate several months of DVOL into one continuous hourly series."""
    frames = []
    for y, m in months:
        try:
            frames.append(fetch_dvol_month(currency, y, m))
        except Exception as exc:
            print(f"  DVOL {y}-{m:02d}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
    if not frames:
        raise RuntimeError("no DVOL months available")
    out = pd.concat(frames, ignore_index=True).sort_values("hour")
    return out.drop_duplicates(subset="hour", keep="last").reset_index(drop=True)


def align_to_blocks(dvol: pd.DataFrame, block_timestamps: pd.Series) -> pd.Series:
    """Latest DVOL observation at or before each block.

    The hour bucket opening at `h` closes at `h + 3600`, so causality requires
    `h + 3600 <= block_timestamp` — the same boundary rule the CEX price
    alignment uses, for the same reason.
    """
    left = pd.DataFrame({"key": block_timestamps.astype("int64") - 3600}).sort_values("key")
    right = dvol[["hour", "close"]].rename(columns={"hour": "dvol_hour", "close": "dvol"})
    merged = pd.merge_asof(
        left, right.sort_values("dvol_hour"), left_on="key", right_on="dvol_hour",
        direction="backward",
    )
    return merged["dvol"].astype(float)
