"""Weekly-rebalanced backtest with full costs from the first run.

Costs are in from run one, never appended later: gas for entry, exit and
re-centring is already inside each pool's weekly net return, and switching
between pools adds an entry and an exit on top.

**A negative result is permitted and is reported as the finding.** "Advertised
LP yields are systematically overstated and this strategy does not recover them"
is a legitimate paper, and given Stage 5 found the underlying positions lost
money in three quarters of all weeks, it is the likely one. The strategy's job
here is avoidance, not selection.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WEEKS_PER_YEAR = 52


@dataclass(frozen=True)
class BacktestResult:
    name: str
    returns: pd.Series
    annualised_return: float
    volatility: float
    sharpe: float
    max_drawdown: float
    turnover: float
    share_invested: float
    n_weeks: int
    total_cost: float = 0.0

    def as_row(self) -> dict:
        return {
            "strategy": self.name, "ann_return": self.annualised_return,
            "volatility": self.volatility, "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown, "turnover": self.turnover,
            "share_invested": self.share_invested, "n_weeks": self.n_weeks,
        }


def _summarise(name: str, r: pd.Series, turnover: float = 0.0,
               share_invested: float = 1.0, total_cost: float = 0.0) -> BacktestResult:
    r = r.dropna()
    if len(r) < 4:
        raise ValueError(f"{name}: only {len(r)} weeks")
    ann = float(r.mean() * WEEKS_PER_YEAR)
    vol = float(r.std(ddof=1) * np.sqrt(WEEKS_PER_YEAR))
    curve = (1 + r).cumprod()
    dd = float((curve / curve.cummax() - 1).min())
    return BacktestResult(
        name=name, returns=r, annualised_return=ann, volatility=vol,
        sharpe=ann / vol if vol > 0 else float("nan"), max_drawdown=dd,
        turnover=turnover, share_invested=share_invested, n_weeks=len(r),
        total_cost=total_cost,
    )


def run_backtest(
    signals: pd.DataFrame, realised: pd.DataFrame, switch_cost: float = 0.00045,
    name: str = "strategy",
) -> BacktestResult:
    """Execute the allocation and charge for changing it.

    `switch_cost` is the round trip of exiting one pool and entering another,
    as a fraction of the notional moved: two transactions of ~$22.39 gas on a
    $100k position. Charged on turnover, so a week that keeps the same
    allocation pays nothing — which is the honest treatment and is what makes a
    high-turnover signal expensive.
    """
    m = signals.merge(realised, on=["week", "pool"], how="inner", suffixes=("", "_r"))
    weekly, turnovers, invested = [], [], []
    prev = pd.Series(dtype=float)

    for week, g in m.groupby("week", sort=True):
        w = g.set_index("pool")["weight"].astype(float)
        ret = g.set_index("pool")["net_return"].astype(float)
        gross = float((w * ret).sum())
        aligned_prev = prev.reindex(w.index).fillna(0.0)
        turn = float((w - aligned_prev).abs().sum())
        weekly.append({"week": week, "ret": gross - turn * switch_cost})
        turnovers.append(turn)
        invested.append(float(w.sum()))
        prev = w

    s = pd.DataFrame(weekly).set_index("week")["ret"]
    return _summarise(name, s, turnover=float(np.mean(turnovers)),
                      share_invested=float(np.mean(invested)),
                      total_cost=float(np.sum(turnovers) * switch_cost))


def benchmark_equal_weight(realised: pd.DataFrame) -> BacktestResult:
    """Always provide, equal weight across pools. The passive LP."""
    s = realised.groupby("week")["net_return"].mean()
    return _summarise("equal-weight LP", s)


def benchmark_best_pool_ex_post(realised: pd.DataFrame) -> BacktestResult:
    """The pool that turned out best, chosen with hindsight.

    Unbeatable by construction and included for exactly that reason: a strategy
    that does not clearly separate from it has not demonstrated selection.
    """
    means = realised.groupby("pool")["net_return"].mean()
    best = means.idxmax()
    s = realised[realised.pool == best].set_index("week")["net_return"]
    return _summarise(f"best single pool ex-post ({best})", s)


def benchmark_hold_tokens(prices: pd.Series) -> BacktestResult:
    """Buy 50/50 ETH and USDC once and never rebalance.

    The weights drift: as ETH appreciates it becomes more than half the
    portfolio, so the return is not simply half the ETH return. That drift is
    the whole difference from the rebalanced benchmark, and computing both the
    same way would collapse them into one number.

    Will usually beat an LP strategy on raw return in a bull market. The claim
    is risk-adjusted, and the deck says so plainly rather than choosing a sample
    where it does not happen.
    """
    p = prices.dropna()
    eth_units, cash = 0.5 / float(p.iloc[0]), 0.5
    value = eth_units * p + cash
    return _summarise("hold 50/50 tokens (drifting)", value.pct_change().dropna())


def benchmark_fifty_fifty_rebalanced(prices: pd.Series) -> BacktestResult:
    """50/50 rebalanced every week — the portfolio LVR is defined against.

    Constant half-weight in the risky asset, so the return is exactly half the
    ETH return each week. This is the reference portfolio in the LVR
    definition, which is why it belongs in the table even though it is not a
    strategy anyone runs.
    """
    return _summarise("50/50 rebalanced weekly", 0.5 * prices.pct_change().dropna())


def report(results: list[BacktestResult], n_trials: int) -> pd.DataFrame:
    """Output 3, with the deflated Sharpe alongside the raw one."""
    from src.utils.stats import deflated_sharpe_ratio

    rows = []
    for r in results:
        row = r.as_row()
        try:
            d = deflated_sharpe_ratio(r.returns, n_trials=n_trials,
                                      periods_per_year=WEEKS_PER_YEAR)
            row["deflated_sharpe_prob"] = d["deflated_sharpe_prob"]
            row["beats_null"] = d["beats_null"]
            row["skew"] = d["skew"]
        except Exception:
            row["deflated_sharpe_prob"] = float("nan")
            row["beats_null"] = False
            row["skew"] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)
