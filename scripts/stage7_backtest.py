"""Stage 7 — the allocation strategy, backtested with full costs.

Engine: predict the components, not the total. LVR from the closed form with a
HAR-RV variance forecast (H6 winner); fees from LightGBM (which beats its own
baselines where predicting net directly does not). Allocate where the predicted
net clears a threshold.

All predictions are out-of-sample under the same purged, embargoed folds used
in Stage 6.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.model.forecast import fit_lightgbm
from src.model.purged_cv import PurgedKFold
from src.model.volatility import har_rv_forecast
from src.strategy.allocate import allocation_signal
from src.strategy.backtest import (benchmark_best_pool_ex_post,
                                   benchmark_equal_weight,
                                   benchmark_fifty_fifty_rebalanced,
                                   benchmark_hold_tokens, report, run_backtest)
from src.utils.config import REPO_ROOT
from src.utils.speclog import count_specifications, log_specification

PANEL = REPO_ROOT / "data" / "processed" / "weekly_panel_all.parquet"
DAILY = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
#: ETH/USDC 100bp is excluded: a $100k position is 113% of its active liquidity,
#: so it is not a price-taker and its returns are not measurements (DECISIONS 5.7).
POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp", "WBTC_ETH_30bp", "USDC_USDT_1bp")
NOTIONAL = 100_000.0
GAS_WEEK = 22.39 / NOTIONAL          # one re-centre a week, as a fraction

#: Chosen on out-of-sample fee-prediction R² *before* any backtest was run, and
#: logged as a specification. Seven features on 352 pool-weeks overfits: the
#: wider set scores -0.037 out of sample against +0.083 for this one. Selecting
#: it on backtest performance instead would be the multiple-testing trap the
#: deflated Sharpe exists to punish.
FEE_FEATURES = ["fees_lag1", "fees_usd", "realized_vol_7d", "swaps_7d"]


def variance_series(pool: str) -> pd.DataFrame:
    d = pd.read_parquet(DAILY)
    d = d[d.pool == pool].copy()
    d.index = pd.to_datetime(d["day"], utc=True)
    rv = (d["sigma_annual"].astype(float) ** 2).sort_index()
    out = pd.DataFrame({"rv_now": rv.resample("W").mean(),
                        "rv_forecast": har_rv_forecast(rv, 7, 60).resample("W").last()})
    out["pool"] = pool
    return out.reset_index().rename(columns={out.index.name or "index": "week", "day": "week"})


def main() -> int:
    panel = pd.read_parquet(PANEL)
    panel = panel[panel.pool.isin(POOLS)].copy()
    panel["target_fees_next"] = panel.groupby("pool")["fees_usd"].shift(-1)

    fc = pd.concat([variance_series(p) for p in POOLS], ignore_index=True)
    d = panel.merge(fc, on=["pool", "week"], how="left")
    d = d.dropna(subset=["target_net_next", "target_fees_next", "rv_forecast",
                         "rv_now"] + FEE_FEATURES).sort_values("week").reset_index(drop=True)

    cv = PurgedKFold(n_splits=5, purge_days=7, embargo_days=7)
    X = d[FEE_FEATURES].astype(float)
    X.index = pd.DatetimeIndex(d["week"])

    # --- fees: LightGBM, out-of-sample ------------------------------------- #
    y_fees = pd.Series(d["target_fees_next"].astype(float).to_numpy(), index=X.index)
    fee_model = fit_lightgbm(X, y_fees, cv, name="fees LightGBM")
    d["pred_fees"] = fee_model.predictions.reindex(X.index).to_numpy() / NOTIONAL

    # --- LVR: the closed form with a variance forecast ---------------------- #
    d["pred_lvr"] = (d["lvr_analytical_usd"].astype(float)
                     * (d["rv_forecast"].astype(float) / d["rv_now"].astype(float))) / NOTIONAL
    d["pred_gas"] = GAS_WEEK
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["pred_fees", "pred_lvr"])

    realised = d[["week", "pool", "target_net_next"]].rename(
        columns={"target_net_next": "net_return"})

    print("=" * 82)
    print("Stage 7 — allocation strategy, full costs")
    print("=" * 82)
    print(f"\n{len(d):,} pool-weeks, {d.week.min().date()} -> {d.week.max().date()}")
    print(f"engine: LVR from sigma^2/8 + HAR-RV; fees from LightGBM (OOS R^2 "
          f"{fee_model.oos_r2:+.3f})")

    # --- ETH price for the token benchmarks -------------------------------- #
    # The ACTUAL ETH price, not the position value. The position is re-sized to
    # a fixed notional at every re-centring, so its value is anchored near $100k
    # by construction and using it as a price series made "hold tokens" and
    # "50/50 rebalanced" come out identical — a tell that neither was measuring
    # the token.
    # The daily LVR table does not carry the price, so take it from the derived
    # layer, which does.
    from src.build.derived import available_months, load_derived
    from src.utils.config import pool as get_pool

    spec = get_pool(POOLS[0])
    frames = []
    for y, m in available_months(spec):
        g = load_derived(spec, [(y, m)], to_decimal=False)
        frames.append(pd.DataFrame({
            "ts": pd.to_datetime(g["block_timestamp"].astype("int64"), unit="s", utc=True),
            "eth": g["cex_price"].astype(float),
        }))
    prices = pd.concat(frames, ignore_index=True).set_index("ts").sort_index()
    eth_weekly = prices["eth"].resample("W").last().dropna()
    eth_weekly = eth_weekly[(eth_weekly.index >= d.week.min())
                            & (eth_weekly.index <= d.week.max())]
    print(f"ETH over the backtest: ${eth_weekly.iloc[0]:,.0f} -> ${eth_weekly.iloc[-1]:,.0f} "
          f"({eth_weekly.iloc[-1] / eth_weekly.iloc[0] - 1:+.1%})")

    results = []
    for thr, scheme, label in ((0.0, "proportional", "strategy (net > 0, prop.)"),
                               (0.0, "equal", "strategy (net > 0, equal)"),
                               (0.002, "proportional", "strategy (net > 0.2%/wk)")):
        sig = allocation_signal(d[["week", "pool", "pred_fees", "pred_lvr", "pred_gas"]],
                                threshold=thr, scheme=scheme)
        results.append(run_backtest(sig, realised, name=label))
        log_specification(stage="7", component="allocation_backtest",
                          params={"threshold": thr, "scheme": scheme,
                                  "engine": "theory_lvr+lgbm_fees"},
                          metric_name="sharpe", metric_value=results[-1].sharpe)

    results.append(benchmark_equal_weight(realised))
    results.append(benchmark_best_pool_ex_post(realised))
    try:
        results.append(benchmark_hold_tokens(eth_weekly))
        results.append(benchmark_fifty_fifty_rebalanced(eth_weekly))
    except Exception as exc:
        print(f"  token benchmarks unavailable: {exc}")

    n_trials = count_specifications()
    t = report(results, n_trials=n_trials)
    print(f"\n=== Output 3: backtest, {n_trials} specifications logged ===\n")
    show = t.copy()
    for c in ("ann_return", "volatility", "max_drawdown", "share_invested"):
        show[c] = show[c].map(lambda v: f"{v:+.1%}" if pd.notna(v) else "n/a")
    for c in ("sharpe", "turnover", "deflated_sharpe_prob", "skew"):
        show[c] = show[c].map(lambda v: f"{v:.3f}" if pd.notna(v) else "n/a")
    print(show[["strategy", "ann_return", "volatility", "sharpe", "max_drawdown",
                "turnover", "share_invested", "deflated_sharpe_prob",
                "beats_null"]].to_string(index=False))

    out = REPO_ROOT / "outputs" / "tables"
    t.to_csv(out / "stage7_backtest.csv", index=False)
    sig.to_csv(out / "allocation_signal.csv", index=False)
    print(f"\nwrote outputs/tables/stage7_backtest.csv and allocation_signal.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
