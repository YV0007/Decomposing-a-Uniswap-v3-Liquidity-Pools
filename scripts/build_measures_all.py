"""Daily realised measures for every CEX reference symbol the pools use.

HAR-Q needs realised quarticity, which HAR-RV does not, so the measures have to
be built per reference series rather than read off the derived tables.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.fetch.binance_data import load_klines_1s
from src.model.volatility import daily_realised_measures, to_sampled_prices
from src.utils.config import REPO_ROOT, pools

def months(a=(2023,1), b=(2026,7)):
    out,(y,m)=[],a
    while (y,m)<=b:
        out.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    return out

def main() -> int:
    symbols = sorted({s.cex_symbol for s in pools("all")})
    for sym in symbols:
        dest = REPO_ROOT/"data"/"processed"/f"realised_measures_{sym}.parquet"
        if dest.exists():
            print(f"  {sym}: cached"); continue
        frames=[]
        for y,m in months():
            try:
                px=to_sampled_prices(load_klines_1s(sym,y,m),5)
                frames.append(daily_realised_measures(px,5))
            except Exception as exc:
                print(f"  {sym} {y}-{m:02d}: {type(exc).__name__}", flush=True)
        if not frames:
            print(f"  {sym}: nothing built"); continue
        out=pd.concat(frames).sort_index()
        out=out[~out.index.duplicated(keep="last")]
        out.to_parquet(dest)
        print(f"  {sym}: {len(out):,} days", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
