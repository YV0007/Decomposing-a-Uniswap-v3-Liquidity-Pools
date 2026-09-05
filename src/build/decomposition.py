"""Assemble the headline table.

    net_return = fees - LVR - MEV_adjustment - gas - funding (if hedged)

All annualised on the single convention in `config.yaml`, all per pool per
period, all with confidence intervals. Both variants reported; delta-hedged
leads, raw is the robustness column.

This produces Output 1 — the decomposition table, and the paper's headline
claim: advertised APR is gross of costs the LP actually pays.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd


@dataclass(frozen=True)
class Decomposition:
    """One row of Output 1."""

    pool_id: str
    fee_tier_bps: int
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    variant: str                 # 'delta_hedged' | 'raw'
    advertised_apr: Decimal      # what the LP is actually shown
    fees: Decimal
    lvr: Decimal                 # negative contribution
    mev: Decimal                 # negative contribution
    gas: Decimal                 # negative contribution
    funding: Decimal             # hedged variant only
    net: Decimal
    net_ci_low: Decimal
    net_ci_high: Decimal

    def check_identity(self, tol: Decimal = Decimal("1e-9")) -> None:
        """The components must sum to net. A sign error here voids the table."""
        raise NotImplementedError("Stage 5.1")


def decompose(
    fees: pd.Series, lvr, mev: pd.Series, gas: pd.Series,
    funding: pd.Series | None, pool_value: pd.Series, variant: str,
) -> Decomposition:
    """Combine the components into one annualised row."""
    raise NotImplementedError("Stage 5.1")


def decomposition_table(pool_ids: list[str], config: dict) -> pd.DataFrame:
    """Output 1 across the universe: advertised APR beside realised net return.

    If low-fee tiers prove systematically loss-making while high-fee tiers do
    not, that is a clean quantified finding that contradicts what LPs are shown.
    """
    raise NotImplementedError("Stage 5.1 — H2")


def fee_tier_experiment(pool_ids: list[str], config: dict) -> pd.DataFrame:
    """H4: ETH/USDC at 5 / 30 / 100bp. Same asset, same volatility, different fee.

    Prediction: higher tiers earn less gross but suffer proportionally less
    LVR, because arbitrage only fires once the price gap exceeds the fee. The
    net ranking is an empirical question, not a prediction.
    """
    raise NotImplementedError("Stage 5.2 — H4")


def gate_signs_and_magnitudes(table: pd.DataFrame) -> dict:
    """Stage 5 sanity checks before anything is reported.

    Net return positive in every pool means LVR was probably not subtracted, or
    a sign is flipped. Fees above the subgraph mean accrual while out of range.
    """
    raise NotImplementedError("Stage 5.3")
