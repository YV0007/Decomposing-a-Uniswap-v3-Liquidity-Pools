"""Does leaving the range explain the closed form's over-prediction? — the one
question Section 6.3 of the paper left open.

`analytical_lvr_rate` already handles a concentrated range exactly: |dn/dS| is
taken on the position's own amount function, so it falls to zero at the
boundaries. Range exhaustion therefore cannot be a *pointwise* error. The
remaining candidate is an inconsistency of frequency: sigma^2 is a daily
aggregate while |dn/dS| is evaluated at sampled prices, so on a day whose move
is one-directional the formula charges the whole day's variance against a
sensitivity the position no longer had once it converted.

That has a sharp test. Two days can share a realised variance and differ
completely in shape: one trends 15% and leaves a +/-10% range, the other
oscillates and never leaves it. Only the first should over-predict.

    trend share = |sum of log returns| / sqrt(sum of squared log returns)

is 1 for a pure trend and near 0 for a pure round trip. If the mechanism is
real, the ratio of realised to predicted LVR falls with it at fixed volatility.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.fetch.binance_data import load_klines_1s
from src.utils.config import REPO_ROOT

CACHE = REPO_ROOT / "data" / "processed" / "daily_shape.parquet"
OUT = REPO_ROOT / "outputs" / "tables"
SYMS = {"ETH_USDC_5bp": "ETHUSDT", "ETH_USDC_30bp": "ETHUSDT",
        "WBTC_USDC_30bp": "BTCUSDT"}


def months(a=(2023, 1), b=(2026, 7)):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def daily_shape(sym: str) -> pd.DataFrame:
    rows = []
    for y, m in months():
        try:
            px = load_klines_1s(sym, y, m)
        except Exception:
            continue
        s = pd.Series(px["close"].astype(float).to_numpy(),
                      index=pd.to_datetime(px["second"].to_numpy(), unit="s",
                                           utc=True)).sort_index()
        r = np.log(s.resample("300s", label="right", closed="right")
                    .last().dropna()).diff().dropna()
        g = r.groupby(r.index.date)
        rows.append(pd.DataFrame({"rv": g.apply(lambda x: float((x ** 2).sum())),
                                  "drift": g.apply(lambda x: abs(float(x.sum())))}))
        print(f"  shape {sym} {y}-{m:02d}", flush=True)
    out = pd.concat(rows)
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index, utc=True))
    out["symbol"] = sym
    return out.reset_index(names="dayk")


def build() -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    d = pd.concat([daily_shape(s) for s in sorted(set(SYMS.values()))],
                  ignore_index=True)
    d.to_parquet(CACHE, index=False)
    return d


def main() -> int:
    shape = build()
    d = pd.read_parquet(REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet")
    d = d[d.pool.isin(SYMS)].copy()
    d["symbol"] = d.pool.map(SYMS)
    d["dayk"] = pd.DatetimeIndex(pd.to_datetime(d.day.dt.strftime("%Y-%m-%d"), utc=True))
    m = d.merge(shape, on=["dayk", "symbol"], how="inner")
    m = m[(m.lvr_analytical_usd > 0) & (m.lvr_empirical_usd > 0) & (m.rv > 0)].copy()
    m["ratio"] = m.lvr_empirical_usd / m.lvr_analytical_usd
    m["trend_share"] = m.drift / np.sqrt(m.rv)
    m["leaves_range"] = m.drift > np.log(1.10)

    print("=" * 84)
    print("RANGE EXHAUSTION — does the shape of the day matter, at fixed variance?")
    print("=" * 84)
    print(f"\n{len(m):,} pool-days across {m.pool.nunique()} pools; "
          f"{int(m.leaves_range.sum())} with a one-way move past +/-10%\n")

    rows = []
    print("--- ratio by trend share, within the top volatility quartile ---\n")
    hi = m[m.sigma_annual >= m.sigma_annual.quantile(0.75)].copy()
    hi["tb"] = pd.qcut(hi.trend_share, 4,
                       labels=["most oscillating", "2", "3", "most trending"])
    t = hi.groupby("tb", observed=True).apply(lambda s: pd.Series({
        "n": len(s), "median_sigma": s.sigma_annual.median(),
        "median_trend": s.trend_share.median(),
        "agg_ratio": s.lvr_empirical_usd.sum() / s.lvr_analytical_usd.sum()}),
        include_groups=False)
    print(t.to_string(float_format=lambda v: f"{v:10.3f}"))
    for k, r in t.iterrows():
        rows.append({"test": "trend_quartile_top_vol_quartile", "bucket": str(k),
                     **{c: float(r[c]) for c in t.columns}})

    print("\n--- days that leave the range against days that do not ---\n")
    for lab, g in (("stays in range", m[~m.leaves_range]),
                   ("leaves range", m[m.leaves_range])):
        r = g.lvr_empirical_usd.sum() / g.lvr_analytical_usd.sum()
        print(f"  {lab:16s} n={len(g):5d}  median sigma {g.sigma_annual.median():.3f}"
              f"   ratio {r:.3f}")
        rows.append({"test": "leaves_range", "bucket": lab, "n": len(g),
                     "median_sigma": float(g.sigma_annual.median()),
                     "agg_ratio": float(r)})
    q = m[m.sigma_annual >= m.sigma_annual.quantile(0.95)]
    print("\n  restricted to the top 5% of volatility days, where the two groups"
          "\n  have comparable variance and differ only in shape:")
    for lab, g in (("stays", q[~q.leaves_range]), ("leaves", q[q.leaves_range])):
        if len(g) == 0:
            continue
        r = g.lvr_empirical_usd.sum() / g.lvr_analytical_usd.sum()
        print(f"    {lab:8s} n={len(g):4d}  median sigma {g.sigma_annual.median():.3f}"
              f"   ratio {r:.3f}")
        rows.append({"test": "leaves_range_top5pct_sigma", "bucket": lab, "n": len(g),
                     "median_sigma": float(g.sigma_annual.median()),
                     "agg_ratio": float(r)})

    # A regression is the cleaner statement: does shape matter once variance is held?
    x = np.column_stack([np.ones(len(m)), np.log(m.sigma_annual.to_numpy()),
                         m.trend_share.to_numpy()])
    y = np.log(m.ratio.to_numpy())
    b = np.linalg.lstsq(x, y, rcond=None)[0]
    resid = y - x @ b
    # month-clustered bootstrap on the trend coefficient
    rng = np.random.default_rng(20260908)
    m["period"] = m.day.dt.to_period("M").astype(str)
    by = {p: g for p, g in m.groupby("period")}
    keys = list(by)
    boot = []
    for _ in range(2000):
        s = pd.concat([by[keys[i]] for i in rng.choice(len(keys), len(keys), replace=True)],
                      ignore_index=True)
        xs = np.column_stack([np.ones(len(s)), np.log(s.sigma_annual.to_numpy()),
                              s.trend_share.to_numpy()])
        boot.append(np.linalg.lstsq(xs, np.log(s.ratio.to_numpy()), rcond=None)[0][2])
    boot = np.array(boot)
    lo, hi_ = np.percentile(boot, [2.5, 97.5])
    r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
    print(f"\n--- log(ratio) = a + b1*log(sigma) + b2*trend_share ---\n")
    print(f"  b1 (volatility) = {b[1]:+.4f}")
    print(f"  b2 (trend share) = {b[2]:+.4f}   95% CI [{lo:+.4f}, {hi_:+.4f}]"
          f"   P(b2<0) = {np.mean(boot < 0):.3f}")
    print(f"  R2 = {r2:.3f},  n = {len(m):,}")
    rows.append({"test": "regression", "bucket": "trend_share", "n": len(m),
                 "coef": float(b[2]), "lo": float(lo), "hi": float(hi_),
                 "p_negative": float(np.mean(boot < 0)), "r2": float(r2)})
    verdict = ("supported" if hi_ < 0 else
               "refused" if lo > 0 else "not distinguishable from zero")
    print(f"\n  VERDICT: the range-exhaustion mechanism is {verdict.upper()}.")
    rows.append({"test": "verdict", "bucket": verdict})
    pd.DataFrame(rows).to_csv(OUT / "range_exhaustion.csv", index=False)
    print("\nwrote outputs/tables/range_exhaustion.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
