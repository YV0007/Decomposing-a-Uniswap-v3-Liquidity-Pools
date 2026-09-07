"""Which weekly variance forecast is best? — the direct lever on H7.

The allocation captures 9% of a 15.9pp edge, and the miss is in the LVR arm,
which is `sigma^2/8` fed a variance forecast. Improving the forecast is
therefore the one change that acts directly on the strategy's weakness rather
than around it.

Variants, and the prior each encodes:

- **persistence** — assume next week's variance equals this week's. The bar.
- **EWMA (RiskMetrics)** — one fixed decay constant, nothing fitted.
- **HAR-RV** — daily, weekly and monthly components. The incumbent.
- **HAR-Q** — HAR with the daily term discounted by `sqrt(RQ)`. Encodes that a
  day's realised variance is itself estimated with error, and that the error
  grows with realised quarticity. The most-cited improvement on HAR.
- **HAR-CJ** — continuous and jump components entered separately. `sigma^2/8`
  is derived under a diffusion, so if the continuous part forecasts better than
  total variance, that says something about which part of price movement
  arbitrageurs actually extract.
- **HAR + IV** — adds Deribit DVOL, the only genuinely forward-looking input
  available.

Scored on **QLIKE** as well as RMSE. Variance is a latent, right-skewed target
and squared error over-weights the few explosive days; QLIKE is the standard
robust loss for exactly this problem and can rank differently.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.fetch.binance_data import load_klines_1s
from src.fetch.deribit import load_dvol
from src.model.volatility import (daily_realised_measures, ewma_forecast,
                                  har_family_forecast, to_sampled_prices)
from src.utils.config import REPO_ROOT

SYMBOL = "ETHUSDT"
HORIZON = 7
MEASURES = REPO_ROOT / "data" / "processed" / f"realised_measures_{SYMBOL}.parquet"


def months(a=(2023, 1), b=(2026, 7)):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_measures(force: bool = False) -> pd.DataFrame:
    if MEASURES.exists() and not force:
        return pd.read_parquet(MEASURES)
    frames = []
    for y, m in months():
        try:
            px = to_sampled_prices(load_klines_1s(SYMBOL, y, m), 5)
            frames.append(daily_realised_measures(px, 5))
            print(f"  measures {y}-{m:02d}", flush=True)
        except Exception as exc:
            print(f"  measures {y}-{m:02d}: {type(exc).__name__}", flush=True)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.to_parquet(MEASURES)
    return out


def qlike(pred: pd.Series, actual: pd.Series) -> float:
    """QLIKE loss: `actual/pred − log(actual/pred) − 1`. Zero is perfect.

    Robust to the right skew of variance in a way squared error is not — RMSE
    on a variance series is dominated by a handful of explosive days.
    """
    m = (pred > 0) & (actual > 0) & pred.notna() & actual.notna()
    r = actual[m] / pred[m]
    return float((r - np.log(r) - 1).mean())


def main() -> int:
    print("=== building daily realised measures ===", flush=True)
    ms = build_measures()
    print(f"\n{len(ms):,} days, {ms.index.min().date()} to {ms.index.max().date()}\n")

    target = (ms["rv"].shift(-1).rolling(HORIZON, min_periods=1).mean()
              .shift(-(HORIZON - 1)))

    iv = None
    try:
        dv = load_dvol("ETH", months())
        s = pd.Series(dv["close"].astype(float).to_numpy(),
                      index=pd.to_datetime(dv["hour"], unit="s", utc=True))
        # DVOL is an annualised vol in percent; convert to a daily variance and
        # lag it, so a forecast made at t uses only what was published before t.
        iv = ((s / 100.0) ** 2 / 365.0).resample("D").last().shift(1).rename("iv")
        iv = iv.to_frame()
        print(f"DVOL available for {int(iv['iv'].notna().sum()):,} days\n")
    except Exception as exc:
        print(f"DVOL unavailable ({type(exc).__name__}); skipping the IV variant\n")

    forecasts: dict[str, pd.Series] = {}
    forecasts["persistence"] = ms["rv"].shift(1)
    forecasts["EWMA (λ=0.94)"] = ewma_forecast(ms["rv"])
    for kind, label in (("har", "HAR-RV"), ("harq", "HAR-Q"), ("harcj", "HAR-CJ")):
        forecasts[label] = har_family_forecast(ms, kind, HORIZON)
        print(f"  fitted {label}", flush=True)
    if iv is not None:
        forecasts["HAR-RV + IV"] = har_family_forecast(ms, "har", HORIZON, extra=iv)
        print("  fitted HAR-RV + IV", flush=True)

    # Score every model on the observations all of them could predict.
    common = target.dropna().index
    for f in forecasts.values():
        common = common.intersection(f.dropna().index)
    print(f"\nscored on {len(common):,} common days\n")

    rows = []
    a = target.loc[common]
    for name, f in forecasts.items():
        p = f.loc[common]
        err = p - a
        ss_tot = float(((a - a.mean()) ** 2).sum())
        rows.append({
            "model": name,
            "rmse": float(np.sqrt((err**2).mean())),
            "qlike": qlike(p, a),
            "r2": 1 - float((err**2).sum()) / ss_tot if ss_tot > 0 else np.nan,
            "bias": float((p / a).median() - 1),
        })
    t = pd.DataFrame(rows).sort_values("qlike").reset_index(drop=True)
    base = t[t.model == "HAR-RV"].iloc[0]
    t["qlike_vs_har"] = t["qlike"] / base["qlike"]
    t["rmse_vs_har"] = t["rmse"] / base["rmse"]

    show = t.copy()
    for c in ("rmse",):
        show[c] = show[c].map(lambda v: f"{v:.3e}")
    for c in ("qlike", "r2", "bias", "qlike_vs_har", "rmse_vs_har"):
        show[c] = show[c].map(lambda v: f"{v:8.4f}")
    print(show.to_string(index=False))

    best_q = t.iloc[0]
    best_r = t.sort_values("rmse").iloc[0]
    print(f"\n  best by QLIKE: {best_q.model}  ({best_q.qlike_vs_har:.3f}x HAR-RV)")
    print(f"  best by RMSE : {best_r.model}  ({best_r.rmse_vs_har:.3f}x HAR-RV)")
    if best_q.model != best_r.model:
        print("  -> the two losses disagree, which is why both are reported.")

    t.to_csv(REPO_ROOT / "outputs" / "tables" / "volatility_race.csv", index=False)
    print("\nwrote outputs/tables/volatility_race.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
