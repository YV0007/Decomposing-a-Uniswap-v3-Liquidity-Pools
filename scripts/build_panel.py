"""Build the daily fee series and the weekly forecast panel."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months
from src.build.panel import (assert_every_pool_has_fees, build_weekly_panel,
                            daily_fees, pools_missing_from_cache)
from src.fetch.deribit import load_dvol
from src.utils.config import REPO_ROOT, pools

FEE_CACHE = REPO_ROOT / "data" / "processed" / "daily_fees_all.parquet"
PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel_all.parquet"


def main() -> int:
    # The cache is keyed on nothing, so it must be checked against the *current*
    # pool universe rather than merely existing. Adding a pool once left this
    # file a universe behind; the new pool then merged to zero fees and showed a
    # -57% annual return that no gate caught, because zero is a valid number.
    # Only the missing pools are computed, so growing the universe is cheap.
    cached = pd.read_parquet(FEE_CACHE) if FEE_CACHE.exists() else None
    want = {spec.id for spec in pools("all")}
    missing = pools_missing_from_cache(cached, want)
    if cached is not None and not missing:
        fees = cached
        print(f"fee cache covers all {len(want)} pools")
    else:
        if missing:
            print(f"fee cache missing {sorted(missing)}; building those")
        frames = [cached] if cached is not None else []
        for spec in pools("all"):
            if spec.id not in missing:
                continue
            for y, m in available_months(spec):
                try:
                    frames.append(daily_fees(spec, y, m))
                    print(f"  fees {spec.id} {y}-{m:02d}", flush=True)
                except Exception as exc:
                    print(f"  fees {spec.id} {y}-{m:02d}: {type(exc).__name__} "
                          f"{str(exc)[:60]}", flush=True)
        fees = pd.concat(frames, ignore_index=True)
        fees.to_parquet(FEE_CACHE, index=False)

    # A pool that reaches the panel with no fee rows at all is a silent
    # catastrophe, not a data gap: net return collapses to -LVR.
    assert_every_pool_has_fees(fees, want)

    # The cross-section table covers all five pools; h3_daily only the core three.
    xs = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
    lvr = pd.read_parquet(xs if xs.exists()
                          else REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
    months = available_months(pools("core")[0])
    dv = load_dvol("ETH", months)
    dvol = pd.Series(dv["close"].astype(float).to_numpy(),
                     index=pd.to_datetime(dv["hour"], unit="s", utc=True))

    panel = build_weekly_panel(lvr, fees, dvol=dvol)
    panel.to_parquet(PANEL, index=False)
    print(f"\npanel: {len(panel):,} pool-weeks, {panel.pool.nunique()} pools")
    print(f"  columns: {[c for c in panel.columns if not c.startswith('_')]}")
    usable = panel.dropna(subset=["target_net_next", "realized_vol_30d"])
    print(f"  usable rows after lags and targets: {len(usable):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
