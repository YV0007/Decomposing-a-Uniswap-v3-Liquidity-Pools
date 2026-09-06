"""Build the daily fee series and the weekly forecast panel."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months
from src.build.panel import build_weekly_panel, daily_fees
from src.fetch.deribit import load_dvol
from src.utils.config import REPO_ROOT, pools

FEE_CACHE = REPO_ROOT / "data" / "processed" / "daily_fees.parquet"
PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel.parquet"


def main() -> int:
    if FEE_CACHE.exists():
        fees = pd.read_parquet(FEE_CACHE)
    else:
        frames = []
        for spec in pools("core"):
            for y, m in available_months(spec):
                try:
                    frames.append(daily_fees(spec, y, m))
                    print(f"  fees {spec.id} {y}-{m:02d}", flush=True)
                except Exception as exc:
                    print(f"  fees {spec.id} {y}-{m:02d}: {type(exc).__name__} "
                          f"{str(exc)[:60]}", flush=True)
        fees = pd.concat(frames, ignore_index=True)
        fees.to_parquet(FEE_CACHE, index=False)

    lvr = pd.read_parquet(REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
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
