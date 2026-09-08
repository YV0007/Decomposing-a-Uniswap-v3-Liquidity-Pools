"""The fee cache must be checked against the current pool universe.

These guard a defect that cost a whole analysis run: `build_panel.py` reused
`daily_fees_all.parquet` whenever it existed, and the file predated the sixth
pool. WBTC/USDC merged into the panel with zero fees for all 188 weeks, its net
return became `-LVR`, and it reported -57% a year with 0.0% of weeks positive.

Nothing caught it, because every individual number was valid. Zero fees is what
a quiet day looks like. Only the *pattern* — a pool that is zero throughout —
distinguishes missing data from a quiet market, so that pattern needs its own
assertion rather than a range check.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.build.panel import assert_every_pool_has_fees, pools_missing_from_cache

WANT = {"ETH_USDC_5bp", "WBTC_USDC_30bp", "USDC_USDT_1bp"}


def _fees(rows):
    return pd.DataFrame(rows, columns=["pool", "day", "fees_usd"])


def test_absent_cache_means_every_pool_is_missing():
    assert pools_missing_from_cache(None, WANT) == WANT


def test_empty_cache_means_every_pool_is_missing():
    assert pools_missing_from_cache(_fees([]), WANT) == WANT


def test_cache_a_universe_behind_reports_only_the_new_pool():
    """The exact shape of the defect: a cache built before the pool was added."""
    cached = _fees([("ETH_USDC_5bp", "2024-01-01", 10.0),
                    ("USDC_USDT_1bp", "2024-01-01", 3.0)])
    assert pools_missing_from_cache(cached, WANT) == {"WBTC_USDC_30bp"}


def test_current_cache_reports_nothing_missing():
    cached = _fees([(p, "2024-01-01", 1.0) for p in WANT])
    assert pools_missing_from_cache(cached, WANT) == set()


def test_all_zero_pool_raises():
    """A pool present in the table but zero throughout is missing, not quiet."""
    fees = _fees([("ETH_USDC_5bp", "2024-01-01", 10.0),
                  ("USDC_USDT_1bp", "2024-01-01", 3.0),
                  ("WBTC_USDC_30bp", "2024-01-01", 0.0),
                  ("WBTC_USDC_30bp", "2024-01-02", 0.0)])
    with pytest.raises(ValueError, match="WBTC_USDC_30bp"):
        assert_every_pool_has_fees(fees, WANT)


def test_pool_absent_from_the_table_raises():
    fees = _fees([("ETH_USDC_5bp", "2024-01-01", 10.0),
                  ("USDC_USDT_1bp", "2024-01-01", 3.0)])
    with pytest.raises(ValueError, match="WBTC_USDC_30bp"):
        assert_every_pool_has_fees(fees, WANT)


def test_a_quiet_day_is_still_allowed():
    """Zero on some days must stay legal, or the guard would fire on real data."""
    fees = _fees([("ETH_USDC_5bp", "2024-01-01", 0.0),
                  ("ETH_USDC_5bp", "2024-01-02", 10.0),
                  ("USDC_USDT_1bp", "2024-01-01", 3.0),
                  ("WBTC_USDC_30bp", "2024-01-01", 0.0),
                  ("WBTC_USDC_30bp", "2024-01-02", 7.0)])
    assert_every_pool_has_fees(fees, WANT)


def test_nan_fees_do_not_count_as_priced():
    fees = _fees([("ETH_USDC_5bp", "2024-01-01", 10.0),
                  ("USDC_USDT_1bp", "2024-01-01", 3.0),
                  ("WBTC_USDC_30bp", "2024-01-01", float("nan"))])
    with pytest.raises(ValueError, match="WBTC_USDC_30bp"):
        assert_every_pool_has_fees(fees, WANT)


def test_missing_column_raises_rather_than_passing_vacuously():
    fees = pd.DataFrame({"pool": ["ETH_USDC_5bp"], "day": ["2024-01-01"]})
    with pytest.raises(ValueError, match="fees_usd"):
        assert_every_pool_has_fees(fees, WANT)
