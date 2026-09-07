"""Fetch BTCUSDT perpetual klines and funding — the second hedge leg for WBTC/ETH."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.fetch.binance_data import load_funding_rates, load_perp_klines_1m

def months(a=(2023,1), b=(2026,7)):
    out,(y,m)=[],a
    while (y,m)<=b:
        out.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    return out

def main() -> int:
    ok=fail=0
    for y,m in months():
        for label,fn in (("perp",load_perp_klines_1m),("funding",load_funding_rates)):
            try:
                fn("BTCUSDT",y,m); ok+=1
            except Exception as exc:
                fail+=1
                print(f"  {label} {y}-{m:02d}: {type(exc).__name__}", flush=True)
    print(f"\nBTCUSDT: {ok} files, {fail} unavailable")
    return 0

if __name__ == "__main__":
    sys.exit(main())
