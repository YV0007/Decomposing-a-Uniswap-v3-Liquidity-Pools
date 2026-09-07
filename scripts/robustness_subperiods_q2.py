"""Robustness — subperiod stability, and open question 2 (volatility estimator).

**Subperiods.** A headline that holds only in one regime is not a headline. The
sample covers a 2023 recovery, a 2024-25 cycle and 2026; the decomposition and
the H3 regression are re-run in each.

**Open question 2.** The analytical LVR is linear in variance, so an alternative
estimator rescales it exactly: `analytical(est) = analytical(rv5) * sigma2_est /
sigma2_rv5`. That makes the horse race cheap — compute four variance series and
rescale, rather than rebuilding the whole LVR path four times.

Estimators, and the prior each encodes:
- **5-min RV** (baseline) — the standard compromise against microstructure noise
- **1-min RV** — more observations, more noise; should do worse if noise binds
- **Bipower variation** — jump-robust. `sigma^2/8` is derived under a diffusion,
  and a jump is not arbitraged the way a diffusive drift is, so if bipower wins
  that says the theory's continuity assumption is where it loses.
- **Garman-Klass** — range-based, more efficient per observation, gap-sensitive
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.fetch.binance_data import load_klines_1s
from src.model.volatility import (bipower_variation, garman_klass, realized_variance,
                                  to_sampled_prices)
from src.utils.config import REPO_ROOT
from src.utils.stats import newey_west_ols

from src.build.derived import daily_lvr_table

DAILY = daily_lvr_table()
COHORTS = REPO_ROOT / "data" / "tables" if False else REPO_ROOT / "outputs" / "tables"
POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")


def months(a=(2023, 1), b=(2026, 7)):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def variance_estimators() -> pd.DataFrame:
    """Daily annualised variance under each estimator, from the 1s CEX series."""
    frames = []
    for y, m in months():
        try:
            cex = load_klines_1s("ETHUSDT", y, m)
        except Exception:
            continue
        p5 = to_sampled_prices(cex, 5)
        p1 = to_sampled_prices(cex, 1)
        ohlc = pd.DataFrame({
            "open": cex["close"].astype(float).to_numpy(),
            "high": cex["high"].astype(float).to_numpy(),
            "low": cex["low"].astype(float).to_numpy(),
            "close": cex["close"].astype(float).to_numpy(),
        }, index=pd.to_datetime(cex["second"].to_numpy(), unit="s", utc=True)).resample("1min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        d = pd.DataFrame({
            "rv_5min": realized_variance(p5, 5, 24).resample("D").mean(),
            "rv_1min": realized_variance(p1, 1, 24).resample("D").mean(),
            "bipower": bipower_variation(p5, 5, 24).resample("D").mean(),
            "garman_klass": garman_klass(ohlc, 24).resample("D").mean(),
        })
        frames.append(d)
        print(f"  variance {y}-{m:02d}", flush=True)
    return pd.concat(frames).sort_index()


def h3_fit(d: pd.DataFrame, col: str = "lvr_analytical_usd") -> dict:
    g = d[(d[col] > 0) & d["lvr_empirical_usd"].notna()]
    if len(g) < 60:
        return {}
    f = newey_west_ols(g["lvr_empirical_usd"], g[col])
    return {"n": f.n_obs, "beta": f.beta, "se": f.beta_se, "r2": f.r_squared,
            "p_beta_eq_1": f.beta_equals(1.0),
            "ratio": g["lvr_empirical_usd"].sum() / g[col].sum()}


def main() -> int:
    daily = pd.read_parquet(DAILY)
    daily = daily[daily.pool.isin(POOLS)].copy()
    daily["day"] = pd.to_datetime(daily["day"], utc=True)

    # ------------------------------------------------------- subperiods ---- #
    print("=" * 84)
    print("SUBPERIOD STABILITY — H3 regression by year")
    print("=" * 84)
    rows = []
    for year, g in daily.groupby(daily["day"].dt.year):
        r = h3_fit(g)
        if r:
            r["period"] = str(year)
            rows.append(r)
    r_all = h3_fit(daily); r_all["period"] = "full sample"
    rows.append(r_all)
    t = pd.DataFrame(rows)[["period", "n", "beta", "se", "r2", "p_beta_eq_1", "ratio"]]
    print(t.to_string(index=False, float_format=lambda v: f"{v:9.4f}"))
    print("\n  beta is the theory's slope; 1.0 is the prediction, ratio is the level match")

    # volatility-regime split
    print("\n--- by volatility regime (terciles of daily sigma) ---")
    daily["regime"] = pd.qcut(daily["sigma_annual"], 3, labels=["calm", "middle", "volatile"])
    reg = []
    for name, g in daily.groupby("regime", observed=True):
        r = h3_fit(g)
        if r:
            r["period"] = str(name)
            reg.append(r)
    print(pd.DataFrame(reg)[["period", "n", "beta", "r2", "ratio"]].to_string(
        index=False, float_format=lambda v: f"{v:9.4f}"))

    # ------------------------------------------- Q2: which estimator? ------ #
    print("\n" + "=" * 84)
    print("OPEN QUESTION 2 — which volatility estimator best matches empirical LVR?")
    print("=" * 84)
    var = variance_estimators()
    var.index = pd.to_datetime(var.index, utc=True)
    m = daily.merge(var, left_on="day", right_index=True, how="left")
    m["rv_base"] = m["sigma_annual"].astype(float) ** 2

    res = []
    for est in ("rv_5min", "rv_1min", "bipower", "garman_klass"):
        scaled = m["lvr_analytical_usd"] * (m[est] / m["rv_base"])
        g = m.assign(scaled=scaled).replace([np.inf, -np.inf], np.nan).dropna(subset=["scaled"])
        r = h3_fit(g, "scaled")
        if r:
            r["estimator"] = est
            res.append(r)
    q2 = pd.DataFrame(res)[["estimator", "n", "beta", "se", "r2", "p_beta_eq_1", "ratio"]]
    q2["beta_error"] = (q2["beta"] - 1).abs()
    q2 = q2.sort_values("beta_error")
    print(q2.to_string(index=False, float_format=lambda v: f"{v:9.4f}"))
    best = q2.iloc[0]
    print(f"\n  closest to beta = 1: {best.estimator} (beta {best.beta:.3f}), "
          f"highest R²: {q2.sort_values('r2', ascending=False).iloc[0].estimator}")

    out = REPO_ROOT / "outputs" / "tables"
    t.to_csv(out / "robustness_subperiods.csv", index=False)
    pd.DataFrame(reg).to_csv(out / "robustness_regimes.csv", index=False)
    q2.to_csv(out / "q2_volatility_estimators.csv", index=False)
    print(f"\nwrote robustness_subperiods.csv, robustness_regimes.csv, q2_volatility_estimators.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
