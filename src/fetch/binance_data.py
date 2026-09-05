"""Binance public data dumps — the CEX reference price LVR is defined against.

Bulk download from `data.binance.vision`. No API key, no cost, no rate limit.

Granularity choice
------------------
The stated baseline rule is "the last CEX trade at or before the block
timestamp". Aggregate trades give that exactly, but cost ~195 MB per month
(~7 GB over the sample) and tens of millions of rows, of which we consume one
per ~12 s block.

A 1-second kline's ``close`` **is** the last trade in that second, so 1s klines
carry the same information at the resolution we consume it, for ~59 MB per
month. They are the primary source; aggregate trades are downloaded for single
days to validate that the substitution changes nothing.

**The boundary matters.** The kline for second ``s`` covers ``[s, s+1)``, so its
close may be timestamped *after* ``s``. For a block at timestamp ``T``, using
the kline for second ``T`` would admit up to one second of lookahead. The
correct kline is ``s = T - 1``, whose close is strictly before ``T``. This is
handled in `src.build.align`, and asserted in `tests/test_no_lookahead.py`.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
AGG_TRADE_COLUMNS = [
    "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
    "transact_time", "is_buyer_maker", "is_best_match",
]


def _cache_dir() -> Path:
    from src.utils.config import REPO_ROOT

    d = REPO_ROOT / "data" / "raw" / "binance"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force and dest.stat().st_size > 0:
        print(f"  cache hit: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    print(f"  downloading {url.rsplit('/', 1)[-1]} ...", flush=True)
    with urllib.request.urlopen(url, timeout=600) as r, open(dest, "wb") as fh:
        fh.write(r.read())
    print(f"    -> {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def _read_zipped_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a Binance zip, tolerating the header row newer dumps carry."""
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    head = raw[:200].decode("utf-8", "replace").split("\n", 1)[0]
    has_header = not head.split(",")[0].strip().lstrip("-").isdigit()
    return pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        names=None if has_header else columns,
    )


def _normalise_epoch(series: pd.Series) -> pd.Series:
    """Binance switched some dumps from millisecond to microsecond epochs.

    Detected by magnitude rather than by date, so the correction cannot be
    wrong-footed by a file that does not follow the announced cutover.
    """
    med = float(series.astype("int64").median())
    if med > 1e15:          # microseconds
        return series.astype("int64") // 1000
    return series.astype("int64")


def load_klines_1s(symbol: str, year: int, month: int, force: bool = False) -> pd.DataFrame:
    """One month of 1-second klines. The primary CEX reference series.

    Returns `[second, close, high, low, volume]` where `second` is the unix
    second the kline **opens** — so the close is a trade in `[second, second+1)`.
    """
    fn = f"{symbol}-1s-{year:04d}-{month:02d}.zip"
    url = f"{BASE}/spot/monthly/klines/{symbol}/1s/{fn}"
    df = _read_zipped_csv(_download(url, _cache_dir() / fn, force), KLINE_COLUMNS)
    out = pd.DataFrame(
        {
            "second": _normalise_epoch(df["open_time"]) // 1000,
            "close": df["close"].astype(str),
            "high": df["high"].astype(str),
            "low": df["low"].astype(str),
            "volume": df["volume"].astype(str),
        }
    )
    return out.sort_values("second").reset_index(drop=True)


def load_agg_trades_day(symbol: str, day: date, force: bool = False) -> pd.DataFrame:
    """One day of aggregate trades — the validation source for the kline substitution."""
    fn = f"{symbol}-aggTrades-{day:%Y-%m-%d}.zip"
    url = f"{BASE}/spot/daily/aggTrades/{symbol}/{fn}"
    df = _read_zipped_csv(_download(url, _cache_dir() / fn, force), AGG_TRADE_COLUMNS)
    out = pd.DataFrame(
        {
            "timestamp_ms": _normalise_epoch(df["transact_time"]),
            "price": df["price"].astype(str),
            "quantity": df["quantity"].astype(str),
        }
    )
    return out.sort_values("timestamp_ms").reset_index(drop=True)


def load_funding_rates(symbol: str, year: int, month: int, force: bool = False) -> pd.DataFrame:
    """Realised perpetual funding for the delta-hedged variant.

    Actual realised funding, per the Stage 0 decision — never an assumption.
    Settled 8-hourly, so a month is ~90 rows.
    """
    fn = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    url = f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{fn}"
    df = _read_zipped_csv(_download(url, _cache_dir() / fn, force),
                          ["calc_time", "funding_interval_hours", "last_funding_rate"])
    return pd.DataFrame(
        {
            "timestamp_ms": _normalise_epoch(df["calc_time"]),
            "funding_rate": df["last_funding_rate"].astype(str),
            "interval_hours": df["funding_interval_hours"].astype("int64"),
        }
    ).sort_values("timestamp_ms").reset_index(drop=True)


def load_reference_series(symbol: str, months: list[tuple[int, int]]) -> pd.DataFrame:
    """Concatenate several months of 1s klines into one continuous series."""
    frames = [load_klines_1s(symbol, y, m) for y, m in months]
    out = pd.concat(frames, ignore_index=True).sort_values("second")
    return out.drop_duplicates(subset="second", keep="last").reset_index(drop=True)
