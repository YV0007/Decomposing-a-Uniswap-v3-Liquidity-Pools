"""Delta hedge for the primary (delta-hedged) variant.

Raw LP return is dominated by whether ETH went up over the sample. Hedging
strips that directional beta and leaves the market-making return the paper is
actually about: `fees - LVR - MEV - funding`.

Specification fixed in `DECISIONS.md` 0.1: Binance ETH perpetual, daily
rebalance at baseline, realised funding, and a hedge ratio taken from the v3
position's own delta — **not** 0.5.

Why not 0.5
-----------
A v3 position's delta sweeps from fully-risky at the bottom of its range to
fully-cash at the top. A constant hedge would leave a residual that grows
precisely when the position is most stressed, which is the opposite of what a
hedge is for. The delta comes from `position.risky_delta`, evaluated at the
pool price.

What the hedge costs
--------------------
Three things, all of which are measured rather than assumed:

- **Funding**, paid or received on the perpetual leg every 8 hours at the rate
  the exchange actually published.
- **Hedging error**, the unhedged residual between rebalances. This is open
  question 7: if it is large relative to the LVR being measured, the hedged
  variant stops being the cleaner one and the Stage 0 decision has to be
  revisited.
- **Rebalance trading cost**, taker fees on the perp. No on-chain gas — the
  hedge lives on a centralised venue.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from src.build.position import Position, risky_delta
from src.utils.config import PoolSpec

SECONDS_PER_YEAR = 365 * 24 * 3600
FUNDING_INTERVAL_SECONDS = 8 * 3600

#: Binance USD-M taker fee. Applied to the notional traded at each rebalance.
DEFAULT_TAKER_FEE = Decimal("0.0004")


@dataclass(frozen=True)
class HedgeResult:
    """Hedge leg outcome over the position's life, annualised as fractions."""

    n_rebalances: int
    funding_paid_usd: Decimal          # positive = cost to the hedger
    hedge_pnl_usd: Decimal             # mark-to-market on the short leg
    trading_cost_usd: Decimal
    mean_abs_hedge_error_eth: Decimal
    max_abs_hedge_error_eth: Decimal
    mean_abs_error_usd: Decimal
    days: Decimal
    base_usd: Decimal

    def annualised(self, x: Decimal) -> Decimal:
        return x / self.base_usd * Decimal(365) / self.days

    @property
    def funding(self) -> Decimal:
        return self.annualised(self.funding_paid_usd)

    @property
    def trading_cost(self) -> Decimal:
        return self.annualised(self.trading_cost_usd)

    @property
    def pnl(self) -> Decimal:
        return self.annualised(self.hedge_pnl_usd)


def rebalance_timestamps(start: int, end: int, freq_seconds: int) -> list[int]:
    """Rebalance points on a fixed schedule."""
    if freq_seconds <= 0:
        raise ValueError("freq_seconds must be positive")
    return list(range(start, end + 1, freq_seconds))


def _at_or_before(df: pd.DataFrame, key_col: str, targets: list[int]) -> pd.DataFrame:
    """Latest row at or before each target. Backward join; never forward."""
    left = pd.DataFrame({key_col: targets}).sort_values(key_col)
    return pd.merge_asof(left, df.sort_values(key_col), on=key_col, direction="backward")


def accrued_funding(
    funding: pd.DataFrame, start_ts: int, end_ts: int, short_notional_usd: Decimal
) -> Decimal:
    """Funding paid on a short perp position held between two timestamps.

    A **short** pays when funding is positive (longs pay shorts is the negative
    case), so the sign convention here is: positive result means the hedger
    paid. Settlements are point events every 8 hours, so only settlements that
    actually fall inside the interval are charged — pro-rating a settlement the
    position was not open for would fabricate carry.
    """
    if funding.empty:
        return Decimal(0)
    ts = funding["timestamp_ms"].astype("int64") // 1000
    inside = funding[(ts > start_ts) & (ts <= end_ts)]
    total = Decimal(0)
    for rate in inside["funding_rate"]:
        total += -short_notional_usd * Decimal(str(rate))
    return total


def simulate_hedge(
    blocks: pd.DataFrame, position: Position, spec: PoolSpec, perp: pd.DataFrame,
    funding: pd.DataFrame, freq_seconds: int = 86_400,
    taker_fee: Decimal = DEFAULT_TAKER_FEE, base_usd: Decimal | None = None,
) -> HedgeResult:
    """Run a discretely rebalanced short perp hedge against the position's delta.

    `blocks` needs `block_timestamp`, `sqrt_price_x96` and `price`; `perp` needs
    `minute` and `close`; `funding` needs `timestamp_ms` and `funding_rate`.

    The hedge is sized at each rebalance to the position's delta *at that
    moment* and then held fixed until the next one — which is what creates the
    hedging error the sweep measures.
    """
    if blocks.empty:
        raise ValueError("no blocks to hedge")
    base = base_usd or position.notional_usd
    start, end = int(blocks["block_timestamp"].iloc[0]), int(blocks["block_timestamp"].iloc[-1])
    stamps = rebalance_timestamps(start, end, freq_seconds)

    perp_idx = perp.rename(columns={"minute": "block_timestamp"})[["block_timestamp", "close"]]
    marks = _at_or_before(perp_idx, "block_timestamp", stamps + [end])
    perp_price = [Decimal(str(p)) if pd.notna(p) else None for p in marks["close"]]

    state = _at_or_before(
        blocks[["block_timestamp", "sqrt_price_x96"]], "block_timestamp", stamps + [end]
    )

    short_eth = Decimal(0)
    funding_total = Decimal(0)
    pnl = Decimal(0)
    trading = Decimal(0)
    n_rebalances = 0

    for i in range(len(stamps)):
        ts = stamps[i]
        p_now = perp_price[i]
        if p_now is None or pd.isna(state["sqrt_price_x96"].iloc[i]):
            continue
        target = risky_delta(position, int(state["sqrt_price_x96"].iloc[i]), spec)

        # Carry the existing short to this point before resizing.
        if short_eth != 0:
            prev_price = perp_price[i - 1]
            if prev_price is not None:
                pnl += short_eth * (prev_price - p_now)      # short gains when price falls
                funding_total += accrued_funding(funding, stamps[i - 1], ts, short_eth * p_now)

        traded = abs(target - short_eth)
        trading += traded * p_now * taker_fee
        short_eth = target
        n_rebalances += 1

    # Carry the final leg to the end of the sample.
    if short_eth != 0 and perp_price[-1] is not None and perp_price[-2] is not None:
        pnl += short_eth * (perp_price[-2] - perp_price[-1])
        funding_total += accrued_funding(funding, stamps[-1], end, short_eth * perp_price[-1])

    err = hedging_error(blocks, position, spec, stamps, short_schedule=None)

    days = Decimal(max(1, end - start)) / Decimal(86400)
    return HedgeResult(
        n_rebalances=n_rebalances,
        funding_paid_usd=funding_total,
        hedge_pnl_usd=pnl,
        trading_cost_usd=trading,
        mean_abs_hedge_error_eth=err["mean_abs_eth"],
        max_abs_hedge_error_eth=err["max_abs_eth"],
        mean_abs_error_usd=err["mean_abs_usd"],
        days=days,
        base_usd=base,
    )


def hedging_error(
    blocks: pd.DataFrame, position: Position, spec: PoolSpec,
    rebalance_stamps: list[int], short_schedule=None,
) -> dict:
    """Unhedged residual between rebalances — open question 7.

    At each block the hedge is short whatever the delta was at the *last*
    rebalance, while the position's delta has moved on. The gap is the exposure
    the hedge is not covering. If its typical size is large relative to the LVR
    being measured, the delta-hedged variant is not the cleaner one and the
    Stage 0 decision has to be revisited — which is why this is measured rather
    than assumed away.
    """
    stamps = sorted(rebalance_stamps)
    held: list[Decimal] = []
    errors: list[Decimal] = []
    errors_usd: list[Decimal] = []

    j = -1
    current = Decimal(0)
    for ts, sqrt_x96, px in zip(
        blocks["block_timestamp"], blocks["sqrt_price_x96"], blocks["price"]
    ):
        ts = int(ts)
        while j + 1 < len(stamps) and stamps[j + 1] <= ts:
            j += 1
            current = risky_delta(position, int(sqrt_x96), spec)
        actual = risky_delta(position, int(sqrt_x96), spec)
        gap = actual - current
        errors.append(abs(gap))
        errors_usd.append(abs(gap) * Decimal(str(px)))
        held.append(current)

    n = Decimal(max(1, len(errors)))
    return {
        "mean_abs_eth": sum(errors, Decimal(0)) / n,
        "max_abs_eth": max(errors) if errors else Decimal(0),
        "mean_abs_usd": sum(errors_usd, Decimal(0)) / n,
        "n_blocks": len(errors),
    }


def rebalance_frequency_sweep(
    blocks: pd.DataFrame, position: Position, spec: PoolSpec,
    perp: pd.DataFrame, funding: pd.DataFrame,
    freqs: tuple[int, ...] = (3600, 86_400, 604_800),
) -> pd.DataFrame:
    """Hedging error and funding cost against rebalance frequency.

    The trade-off is residual exposure against trading cost and funding
    turnover. This sweep is what closes open question 7.
    """
    rows = []
    for f in freqs:
        r = simulate_hedge(blocks, position, spec, perp, funding, freq_seconds=f)
        rows.append({
            "freq_seconds": f,
            "freq_label": {3600: "1h", 86_400: "1D", 604_800: "7D"}.get(f, f"{f}s"),
            "n_rebalances": r.n_rebalances,
            "funding_annualised": float(r.funding),
            "trading_cost_annualised": float(r.trading_cost),
            "hedge_pnl_annualised": float(r.pnl),
            "mean_abs_error_eth": float(r.mean_abs_hedge_error_eth),
            "mean_abs_error_usd": float(r.mean_abs_error_usd),
            "max_abs_error_eth": float(r.max_abs_hedge_error_eth),
        })
    return pd.DataFrame(rows)
