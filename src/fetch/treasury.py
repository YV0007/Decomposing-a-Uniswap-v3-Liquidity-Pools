"""Daily US Treasury bill rates — the cash alternative an LP position gives up.

Every Sharpe ratio in this project was computed as `mean/sd`, which measures
return against *zero*. A liquidity position ties up real capital, so the honest
benchmark is a short Treasury bill, and over 2023-2026 that was not a rounding
error: the 4-week bill paid above 5% for much of the sample.

FRED is unreachable from the machine this was built on, so the series comes from
the Treasury's own daily XML feed, which needs no key. The published field is a
**coupon-equivalent yield in per cent per annum**; it is converted to a decimal
rate here and to a per-period rate at the point of use, never earlier.

The 4-week bill is the baseline because the position is rebalanced weekly. The
13-week series is carried alongside so the choice can be shown not to matter.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

import pandas as pd

from src.utils.config import REPO_ROOT

CACHE = REPO_ROOT / "data" / "raw" / "treasury_bill_rates.parquet"
URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
       "interest-rates/pages/xml?data=daily_treasury_bill_rates"
       "&field_tdr_date_value={year}")
#: Coupon-equivalent yields. "CLOSE" is the discount rate and is NOT the return
#: an investor earns; using it would understate the cash benchmark by ~10bp.
FIELDS = {"rf_4wk": "ROUND_B1_YIELD_4WK_2", "rf_13wk": "ROUND_B1_YIELD_13WK_2"}
_ENTRY = re.compile(r"<m:properties>(.*?)</m:properties>", re.S)


def _field(block: str, tag: str) -> float | None:
    m = re.search(rf"<d:{tag}[^>]*>([^<]*)</d:{tag}>", block)
    if not m or not m.group(1).strip():
        return None
    return float(m.group(1))


def _parse_year(xml: str) -> list[dict]:
    rows = []
    for block in _ENTRY.findall(xml):
        d = re.search(r"<d:INDEX_DATE[^>]*>([^<]*)</d:INDEX_DATE>", block)
        if not d:
            continue
        row = {"date": pd.Timestamp(d.group(1)).tz_localize("UTC")}
        for name, tag in FIELDS.items():
            v = _field(block, tag)
            row[name] = None if v is None else v / 100.0
        rows.append(row)
    return rows


def fetch_bill_rates(years: range | list[int], force: bool = False) -> pd.DataFrame:
    """Daily bill yields as decimal annual rates, indexed by UTC date.

    Cached, because the feed is one request per calendar year and the history
    does not change. A year that fails to download is reported and skipped
    rather than silently producing a shorter series.
    """
    if CACHE.exists() and not force:
        return pd.read_parquet(CACHE)
    frames = []
    for y in years:
        try:
            req = urllib.request.Request(URL.format(year=y),
                                         headers={"User-Agent": "Mozilla/5.0"})
            xml = urllib.request.urlopen(req, timeout=60).read().decode()
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  treasury {y}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
            continue
        rows = _parse_year(xml)
        print(f"  treasury {y}: {len(rows)} business days", flush=True)
        frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("no Treasury data could be fetched")
    out = (pd.concat(frames, ignore_index=True)
             .dropna(subset=["rf_4wk"])
             .drop_duplicates(subset="date")
             .sort_values("date")
             .reset_index(drop=True))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(CACHE, index=False)
    return out


def weekly_risk_free(weeks: pd.DatetimeIndex, column: str = "rf_4wk") -> pd.Series:
    """The per-week cash return for each week ending in `weeks`.

    Bills do not trade at weekends, so the annual rate in force is carried
    forward from the last business day **at or before** each week end — never
    interpolated across it, which would use a rate not yet published.
    """
    r = fetch_bill_rates(range(2022, 2027)).set_index("date")[column].dropna()
    idx = pd.DatetimeIndex(weeks).tz_convert("UTC") if pd.DatetimeIndex(weeks).tz \
        else pd.DatetimeIndex(weeks).tz_localize("UTC")
    aligned = r.reindex(r.index.union(idx)).ffill().reindex(idx)
    return pd.Series(aligned.to_numpy() / 52.0, index=weeks, name="rf_week")
