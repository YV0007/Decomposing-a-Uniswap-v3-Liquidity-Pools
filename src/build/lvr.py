"""Loss-versus-rebalancing — the core of the paper.

**The definition that matters.** LVR is the P&L difference between the AMM
position and a continuously rebalanced portfolio holding the same instantaneous
delta. It is *not* impermanent loss, which compares to holding. Conflating the
two is the standard error in this literature and this module does not make it.

**LVR is also not the sum of arbitrageur profits.** Arbitrageur profit is LVR
minus fees paid minus gas. LVR is gross adverse selection; extraction is what
survives frictions. Both are computed here and the gap between them is part of
H3 — it quantifies how much of the theory survives real-world costs.

Empirical, per block::

    1. pool_price       <- from sqrtPriceX96
    2. cex_price        <- aligned CEX reference (src.build.align)
    3. pool_delta       <- position's token0 holding
    4. rebalanced_delta <- what a continuously rebalanced portfolio holds at cex_price
    5. lvr_increment    <- (cex_price - pool_price) * (pool_delta - rebalanced_delta)

Analytical::

    LVR_rate = sigma**2 / 8    per unit pool value per unit time
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from src.utils.config import PoolSpec


@dataclass(frozen=True)
class LVRResult:
    """Both LVR series plus the extraction actually realised."""

    empirical: pd.Series          # gross adverse selection
    analytical: pd.Series         # sigma^2 / 8
    realised_extraction: pd.Series  # empirical minus arb's fees and gas
    annualised_empirical: Decimal
    annualised_analytical: Decimal


def empirical_lvr(
    position, pool_state: pd.DataFrame, aligned_cex: pd.Series, spec: PoolSpec
) -> pd.Series:
    """Per-block LVR increments from the pool/CEX price gap.

    Sign convention: positive means value transferred **away from** the LP.
    A negative total is a red flag, not a windfall — see the Stage 3 gate.
    """
    raise NotImplementedError("Stage 3.1")


def realised_extraction(
    lvr_increments: pd.Series, pool_state: pd.DataFrame, gas: pd.DataFrame, spec: PoolSpec
) -> pd.Series:
    """What an arbitrageur actually nets: LVR minus the fee paid minus gas.

    Arbitrage only fires when the gap exceeds fee plus gas, so this series is
    zero on most blocks and the gap to `empirical_lvr` is the frictional wedge
    that H3 is really testing.
    """
    raise NotImplementedError("Stage 3.1")


def analytical_lvr(
    sigma: pd.Series, pool_value: pd.Series, dt_seconds: int, constant: Decimal = Decimal("0.125")
) -> pd.Series:
    """Milionis, Moallemi, Roughgarden & Zhang: ``LVR_rate = sigma**2 / 8``.

    `sigma` is annualised volatility from `src.model.volatility`; which
    estimator to use is open question 2 and is swept, not assumed.
    """
    raise NotImplementedError("Stage 3.2")


def regress_h3(empirical: pd.Series, analytical: pd.Series):
    """H3: ``empirical_LVR = alpha + beta * analytical_LVR + eps``.

    Prediction is beta ~ 1, alpha ~ 0. Reports beta with Newey-West standard
    errors, R-squared, and residual analysis against volatility, liquidity and
    gas — because where the theory breaks is the finding, not an embarrassment.

    This gets its own slide regardless of the outcome.
    """
    raise NotImplementedError("Stage 3.3 — H3")


def gate_lvr_sanity(result: LVRResult, spec: PoolSpec) -> dict:
    """Stage 3 GATE. Four checks, all of which must pass.

    1. Empirical LVR is positive on net — arbitrageurs profit from LPs.
    2. Magnitude is plausible: annualised ETH/USDC LVR in the single-digit to
       low-double-digit percent range. 200% or 0.02% means something is wrong;
       say so rather than reporting it.
    3. Analytical and empirical are the same order of magnitude.
    4. LVR scales with realized volatility in the cross-section.

    Diagnostics on failure: LVR ~ 0 usually means the price alignment is broken
    or the pool price is being compared to itself. LVR enormous usually means
    the decimals are wrong or blocks are double-counted.
    """
    raise NotImplementedError("Stage 3.4 — GATE")
