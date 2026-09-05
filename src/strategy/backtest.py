"""Weekly-rebalanced backtest with full costs from the first run.

Costs are in from run one, never appended later: gas for entry, exit and
re-centring; swap fees to rebalance; hedge funding.

**A negative result is permitted and is reported as the finding.** "Advertised
LP yields are systematically overstated and the strategy does not recover them"
is a legitimate paper, and arguably a more interesting one than a profitable
strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BENCHMARKS = [
    "equal_weight_lp",
    "hold_tokens",
    "fifty_fifty_rebalanced",
    "best_single_pool_ex_post",   # unbeatable by construction; included for honesty
]


@dataclass(frozen=True)
class BacktestResult:
    """Output 3."""

    returns: pd.Series
    annualised_return: float
    volatility: float
    sharpe: float
    deflated_sharpe: float
    n_specifications: int
    max_drawdown: float
    turnover: float
    total_gas_usd: float
    capacity_usd: float


def run_backtest(signals: pd.DataFrame, realised: pd.DataFrame, config: dict) -> BacktestResult:
    """Execute the allocation with full costs."""
    raise NotImplementedError("Stage 7.1")


def run_benchmarks(realised: pd.DataFrame, config: dict) -> dict[str, BacktestResult]:
    """The four benchmarks, on identical cost assumptions.

    Hold-tokens will usually beat the strategy on raw return in a bull market.
    The claim is risk-adjusted, and the deck states that plainly rather than
    choosing a sample where it does not happen.
    """
    raise NotImplementedError("Stage 7.1")


def capacity_estimate(pool_state: pd.DataFrame, config: dict) -> float:
    """Size at which approach B breaks, and at which the position moves the pool.

    Whichever binds first is the capacity. Reported as a number, per Stage 7.3.
    """
    raise NotImplementedError("Stage 7.2")


def report(result: BacktestResult, benchmarks: dict) -> pd.DataFrame:
    """Output 3 table: raw and deflated Sharpe side by side, trial count shown."""
    raise NotImplementedError("Stage 7.2")
