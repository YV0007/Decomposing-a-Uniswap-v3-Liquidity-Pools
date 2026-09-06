"""Allocation and backtest.

The tests that matter are the ones catching a backtest that flatters itself:
costs not charged, weights exceeding capital, or a benchmark that is secretly
the strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.allocate import allocation_signal, normalise_weights
from src.strategy.backtest import (benchmark_equal_weight,
                                   benchmark_fifty_fifty_rebalanced,
                                   benchmark_hold_tokens, run_backtest)


def _preds(n=20):
    weeks = pd.date_range("2023-01-01", periods=n, freq="W", tz="UTC")
    rng = np.random.default_rng(0)
    rows = []
    for w in weeks:
        for pool in ("A", "B"):
            rows.append({"week": w, "pool": pool,
                         "pred_fees": abs(rng.normal(0.004, 0.002)),
                         "pred_lvr": abs(rng.normal(0.004, 0.002)),
                         "pred_gas": 0.0002})
    return pd.DataFrame(rows)


def test_weights_never_exceed_capital():
    s = allocation_signal(_preds(), threshold=0.0)
    assert (s.groupby("week")["weight"].sum() <= 1.0 + 1e-9).all()
    assert (s["weight"] >= 0).all()


def test_all_avoid_week_holds_cash():
    """The point of the strategy is being able to not provide."""
    p = _preds()
    p["pred_lvr"] = p["pred_fees"] + 1.0        # every pool clearly unprofitable
    s = allocation_signal(p, threshold=0.0)
    assert (s["weight"] == 0).all()
    assert (s["signal"] == "AVOID").all()


def test_threshold_reduces_participation():
    p = _preds()
    lo = allocation_signal(p, threshold=0.0)["weight"].sum()
    hi = allocation_signal(p, threshold=0.01)["weight"].sum()
    assert hi < lo


def test_equal_scheme_splits_evenly_among_qualifiers():
    p = _preds(4)
    s = allocation_signal(p, threshold=-1.0, scheme="equal")
    per_week = s.groupby("week")["weight"].nunique()
    assert (per_week == 1).all()


def test_turnover_is_charged():
    """A backtest that does not charge for switching is not a backtest."""
    weeks = pd.date_range("2023-01-01", periods=10, freq="W", tz="UTC")
    sig = pd.DataFrame([{"week": w, "pool": p,
                         "weight": (1.0 if (i % 2 == 0) == (p == "A") else 0.0)}
                        for i, w in enumerate(weeks) for p in ("A", "B")])
    realised = pd.DataFrame([{"week": w, "pool": p, "net_return": 0.0}
                             for w in weeks for p in ("A", "B")])
    free = run_backtest(sig, realised, switch_cost=0.0)
    costly = run_backtest(sig, realised, switch_cost=0.01)
    assert costly.annualised_return < free.annualised_return
    assert costly.turnover > 0


def test_holding_still_costs_nothing():
    weeks = pd.date_range("2023-01-01", periods=10, freq="W", tz="UTC")
    sig = pd.DataFrame([{"week": w, "pool": "A", "weight": 1.0} for w in weeks])
    realised = pd.DataFrame([{"week": w, "pool": "A", "net_return": 0.001} for w in weeks])
    r = run_backtest(sig, realised, switch_cost=0.01)
    assert r.turnover == pytest.approx(0.1, abs=0.15)      # only the initial entry


def test_hold_and_rebalance_benchmarks_differ():
    """They collapse into one number if the price series is wrong — which is how
    a bug in the benchmark was caught."""
    idx = pd.date_range("2023-01-01", periods=60, freq="W", tz="UTC")
    prices = pd.Series(np.exp(np.cumsum(np.random.default_rng(1).normal(0.01, 0.05, 60))) * 1200,
                       index=idx)
    hold = benchmark_hold_tokens(prices)
    reb = benchmark_fifty_fifty_rebalanced(prices)
    assert hold.annualised_return != reb.annualised_return


def test_rebalanced_benchmark_is_exactly_half_the_risky_return():
    idx = pd.date_range("2023-01-01", periods=30, freq="W", tz="UTC")
    prices = pd.Series(np.linspace(1000, 2000, 30), index=idx)
    r = benchmark_fifty_fifty_rebalanced(prices)
    assert r.returns.iloc[0] == pytest.approx(0.5 * (prices.iloc[1] / prices.iloc[0] - 1))


def test_equal_weight_benchmark_is_always_invested():
    realised = pd.DataFrame([
        {"week": w, "pool": p, "net_return": 0.001}
        for w in pd.date_range("2023-01-01", periods=10, freq="W", tz="UTC")
        for p in ("A", "B")])
    r = benchmark_equal_weight(realised)
    assert r.share_invested == 1.0 and r.turnover == 0.0


def test_normalise_weights_handles_all_negative():
    assert normalise_weights(pd.Series([-1.0, -2.0])).sum() == 0.0
