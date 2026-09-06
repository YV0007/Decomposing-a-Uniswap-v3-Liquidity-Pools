"""Loss-versus-rebalancing — the core of the paper.

**The definition that matters.** LVR is the P&L difference between the AMM
position and a continuously rebalanced portfolio holding the same instantaneous
delta. It is *not* impermanent loss, which compares to holding. Conflating the
two is the standard error in this literature and this module does not make it.

**LVR is also not the sum of arbitrageur profits.** Arbitrageur profit is LVR
minus fees paid minus gas. LVR is gross adverse selection; extraction is what
survives frictions. Both are computed here, and the gap between them is part of
H3 — it quantifies how much of the theory survives real-world costs.

Three measures, not two
-----------------------
The plan describes an empirical measure and an analytical one. Separating the
empirical side into two makes H3 sharper, because they answer different
questions:

``lvr_from_cex_path``
    What the LP would have lost if the pool were arbitraged to the CEX price at
    every block. Depends only on the external price path, and is the discrete
    analogue of the continuous theory. **This is the quantity sigma^2/8
    predicts**, and it is what the closed form should be tested against.

``lvr_from_pool_path``
    What the LP actually lost, from the pool price actually moving, marked
    against the contemporaneous external price. Zero on blocks where the pool
    does not move. Can be *negative* when uninformed flow pushes the pool away
    from the external price — which is the LP being paid, and is exactly the
    adverse-selection asymmetry the paper is about.

The gap between the two is the frictional wedge: fees and gas mean arbitrage
does not fire on every block, so the pool is not continuously corrected.

Both are computed on the position's own amount function, so a concentrated v3
range is handled exactly rather than through a full-range approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from src.build.position import Position, amounts_at
from src.utils import precision as pr
from src.utils.config import PoolSpec

SECONDS_PER_YEAR = 365 * 24 * 3600

#: Inter-trade gap beyond which `lvr_from_pool_path` stops being trustworthy.
#: The measure marks a whole pool move at the external price of the *ending*
#: block, which is sound when consecutive trades are seconds apart. Over a
#: multi-hour gap the external price has itself travelled a long way, and the
#: attribution becomes arbitrary. Measured on January 2023: the 5bp pool's p99
#: gap is 72s, the 30bp pool's 2981s, and the 100bp pool's 60500s — so the
#: measure is safe on the first, marginal on the second and meaningless on the
#: third. Ten minutes is roughly where a gap starts to exceed the horizon over
#: which the external price is locally stable.
POOL_PATH_MAX_GAP_SECONDS = 600


@dataclass(frozen=True)
class LVRResult:
    """Per-block LVR series plus the annualised summaries."""

    per_block: pd.DataFrame
    annualised_pool_path: Decimal
    annualised_cex_path: Decimal
    annualised_analytical: Decimal
    annualised_naive_v2: Decimal
    mean_position_value: Decimal
    days: Decimal
    pool_path_stale_share: Decimal = Decimal(0)   # share of |LVR| from long gaps
    pool_path_reliable: bool = True
    #: In-range concentration factor: analytical LVR rate over the textbook
    #: sigma^2/8 rate, compared only on blocks where the position is actually
    #: in range. This is the *pure* amplification concentration causes.
    in_range_concentration_factor: Decimal = Decimal(1)


# --------------------------------------------------------------------------- #
# Valuation against an external price
# --------------------------------------------------------------------------- #

def value_at_external(
    position: Position, sqrt_price_x96: int, external_price: Decimal, spec: PoolSpec,
    numeraire_usd: Decimal | None = None,
) -> Decimal:
    """USD value of the position's holdings, marked at an *external* price.

    The pool price sets *what* the position holds; the external price sets what
    those holdings are worth. Keeping the two separate is the whole mechanism:
    the LP's loss is holding the wrong basket when the outside world has moved.
    """
    a0, a1 = amounts_at(position, sqrt_price_x96)
    q0 = Decimal(a0) / Decimal(10**spec.token0.decimals)
    q1 = Decimal(a1) / Decimal(10**spec.token1.decimals)
    # Without a numeraire the value is denominated in token1 (USDC for an
    # inverted pool, WETH otherwise). That is fine for LVR, which is a
    # difference of two values in the same unit, and wrong for anything that
    # has to be compared with a dollar figure such as gas.
    base = q0 + q1 * external_price if spec.invert_price else q0 * external_price + q1
    if numeraire_usd is None:
        return base
    unit = Decimal(str(numeraire_usd)) if not spec.invert_price else Decimal(1)
    return base * unit


def _sqrt_at_usd(price: Decimal, spec: PoolSpec) -> int:
    return pr.price_to_sqrt_price_x96(
        price, spec.token0.decimals, spec.token1.decimals, spec.invert_price
    )


# --------------------------------------------------------------------------- #
# Empirical LVR
# --------------------------------------------------------------------------- #

def lvr_from_pool_path(
    position: Position, spec: PoolSpec,
    sqrt_prev: int, sqrt_now: int, external_price: Decimal,
) -> Decimal:
    """Value lost by the LP from the pool moving, marked at the external price.

    Positive means value left the LP. Negative means the pool moved *away* from
    the external price — uninformed flow, and the LP was paid for it.

    Zero when the pool does not move, so summing across blocks does not
    double-count a dislocation that merely persists.
    """
    return (
        value_at_external(position, sqrt_prev, external_price, spec)
        - value_at_external(position, sqrt_now, external_price, spec)
    )


def lvr_from_cex_path(
    position: Position, spec: PoolSpec, prev_cex: Decimal, now_cex: Decimal
) -> Decimal:
    """LVR under the assumption of perfect arbitrage at every block.

    The pool is taken to sit at the external price at the end of each block, so
    this depends only on the external price path. Non-negative by construction:
    marking the AMM's holdings at any other price than the one that produced
    them can only cost the LP.

    This is the discrete analogue of the continuous theory, and the series the
    sigma^2/8 closed form is a prediction about.
    """
    s_prev, s_now = _sqrt_at_usd(prev_cex, spec), _sqrt_at_usd(now_cex, spec)
    return (
        value_at_external(position, s_prev, now_cex, spec)
        - value_at_external(position, s_now, now_cex, spec)
    )


# --------------------------------------------------------------------------- #
# Analytical LVR
# --------------------------------------------------------------------------- #

def analytical_lvr_rate(
    position: Position, spec: PoolSpec, price: Decimal, sigma_annual: Decimal,
    rel_bump: Decimal = Decimal("1e-4"),
) -> Decimal:
    """Milionis et al.: ``l = (sigma^2 / 2) * S^2 * |dn/dS|``, USD per year.

    `n(S)` is the position's holding of the risky asset at price `S`, so the
    derivative is taken on the position's own amount function by central
    difference. That handles a concentrated v3 range exactly, including the
    boundaries, where the derivative drops to zero because the position has
    fully converted to one asset and no longer responds to price.

    For a full-range constant-product pool this reduces to `sigma^2 * V / 8`;
    `tests/test_lvr.py` asserts that limit.
    """
    h = price * rel_bump
    n_up = _risky_units(position, _sqrt_at_usd(price + h, spec), spec)
    n_dn = _risky_units(position, _sqrt_at_usd(price - h, spec), spec)
    dn_ds = (n_up - n_dn) / (2 * h)
    return (sigma_annual**2 / 2) * price**2 * abs(dn_ds)


def naive_v2_lvr_rate(position_value: Decimal, sigma_annual: Decimal) -> Decimal:
    """``sigma^2 * V / 8`` applied directly to the position's value.

    The textbook form, stated for a *full-range* constant-product pool. Applied
    to a concentrated v3 position it understates LVR, because concentration
    raises the position's price sensitivity per dollar deployed. Reported
    alongside :func:`analytical_lvr_rate` so the size of that error is visible
    rather than assumed.
    """
    return sigma_annual**2 * position_value / 8


def _risky_units(position: Position, sqrt_price_x96: int, spec: PoolSpec) -> Decimal:
    a0, a1 = amounts_at(position, sqrt_price_x96)
    if spec.invert_price:
        return Decimal(a1) / Decimal(10**spec.token1.decimals)
    return Decimal(a0) / Decimal(10**spec.token0.decimals)


# --------------------------------------------------------------------------- #
# Realised extraction
# --------------------------------------------------------------------------- #

def realised_extraction(
    lvr_increment: Decimal, trade_value_usd: Decimal, fee_rate: Decimal, gas_usd: Decimal
) -> Decimal:
    """What an arbitrageur actually nets: LVR minus the fee paid minus gas.

    Arbitrage only fires when the dislocation exceeds fee plus gas, so this is
    zero on most blocks. The gap to the gross series is the frictional wedge
    H3 is really testing.
    """
    net = lvr_increment - trade_value_usd * fee_rate - gas_usd
    return net if net > 0 else Decimal(0)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def compute_lvr(
    aligned: pd.DataFrame, position: Position, spec: PoolSpec, vol: pd.Series
) -> LVRResult:
    """Per-block LVR on all three measures, plus annualised summaries.

    `aligned` must carry `sqrt_price_x96`, `cex_price`, `block_timestamp` and
    the pool `price`; `vol` is annualised volatility aligned to the same rows.
    """
    rows = []
    prev_sqrt = prev_cex = None
    for sqrt_x96, cex_p, ts, pool_p, sig in zip(
        aligned["sqrt_price_x96"], aligned["cex_price"],
        aligned["block_timestamp"], aligned["price"], vol,
    ):
        if cex_p is None or pd.isna(sig):
            prev_sqrt, prev_cex = int(sqrt_x96), cex_p
            continue
        s_now, c_now = int(sqrt_x96), Decimal(str(cex_p))
        sigma = Decimal(str(sig)).sqrt()

        pool_lvr = (
            Decimal(0) if prev_sqrt is None
            else lvr_from_pool_path(position, spec, prev_sqrt, s_now, c_now)
        )
        cex_lvr = (
            Decimal(0) if prev_cex is None
            else lvr_from_cex_path(position, spec, Decimal(str(prev_cex)), c_now)
        )
        value = value_at_external(position, s_now, c_now, spec)
        rows.append(
            {
                "block_timestamp": int(ts),
                "value_usd": value,
                "sigma_annual": sigma,
                "lvr_pool_path": pool_lvr,
                "lvr_cex_path": cex_lvr,
                "lvr_analytical_rate": analytical_lvr_rate(position, spec, c_now, sigma),
                "lvr_naive_v2_rate": naive_v2_lvr_rate(value, sigma),
            }
        )
        prev_sqrt, prev_cex = s_now, c_now

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("no aligned rows with both a CEX price and a volatility estimate")

    dt = df["block_timestamp"].diff().fillna(0).clip(lower=0)
    df["dt_seconds"] = dt
    df["lvr_analytical"] = [
        r * Decimal(int(s)) / Decimal(SECONDS_PER_YEAR)
        for r, s in zip(df["lvr_analytical_rate"], dt)
    ]
    df["lvr_naive_v2"] = [
        r * Decimal(int(s)) / Decimal(SECONDS_PER_YEAR)
        for r, s in zip(df["lvr_naive_v2_rate"], dt)
    ]

    # How much of the pool-path measure rests on intervals too long to mark
    # credibly? Reported rather than silently included.
    stale = df["dt_seconds"] > POOL_PATH_MAX_GAP_SECONDS
    abs_total = sum((abs(v) for v in df["lvr_pool_path"]), Decimal(0))
    abs_stale = sum((abs(v) for v in df.loc[stale, "lvr_pool_path"]), Decimal(0))
    stale_share = (abs_stale / abs_total) if abs_total > 0 else Decimal(0)

    # Concentration amplification, compared like with like. The whole-period
    # ratio of the two annualised totals is NOT this quantity: the analytical
    # rate is zero out of range while the naive one is not, so over a month
    # spent mostly out of range two large effects — ~20x amplification while in
    # range, and a naive formula charging LVR when the position cannot lose any
    # — very nearly cancel. Reporting that near-cancellation as "the
    # concentration effect" would understate the amplification by an order of
    # magnitude.
    live = df["lvr_analytical_rate"] > 0
    if live.any():
        num = sum(df.loc[live, "lvr_analytical_rate"], Decimal(0))
        den = sum(df.loc[live, "lvr_naive_v2_rate"], Decimal(0))
        conc = num / den if den > 0 else Decimal(1)
    else:
        conc = Decimal(1)

    span = Decimal(int(df["block_timestamp"].iloc[-1] - df["block_timestamp"].iloc[0]))
    days = span / Decimal(86400)
    mean_value = sum(df["value_usd"], Decimal(0)) / Decimal(len(df))

    def ann(col: str) -> Decimal:
        total = sum(df[col], Decimal(0))
        return total / mean_value * Decimal(SECONDS_PER_YEAR) / span

    return LVRResult(
        per_block=df,
        annualised_pool_path=ann("lvr_pool_path"),
        annualised_cex_path=ann("lvr_cex_path"),
        annualised_analytical=ann("lvr_analytical"),
        annualised_naive_v2=ann("lvr_naive_v2"),
        mean_position_value=mean_value,
        days=days,
        pool_path_stale_share=stale_share,
        pool_path_reliable=stale_share < Decimal("0.25"),
        in_range_concentration_factor=conc,
    )


def gate_lvr_sanity(result: LVRResult, bounds=(Decimal("0.005"), Decimal("0.60"))) -> dict:
    """Stage 3 GATE.

    1. LVR is positive on net — arbitrageurs profit from LPs.
    2. Magnitude is plausible. Outside single-digit to low-double-digit percent
       annualised on ETH/USDC, something is wrong; say so rather than report it.
    3. Analytical and empirical are the same order of magnitude.

    Diagnostics on failure: LVR near zero usually means the price alignment is
    broken or the pool price is being compared to itself. LVR enormous usually
    means the decimals are wrong or blocks are double-counted.
    """
    lo, hi = bounds
    checks = {
        "pool_path_measurable": result.pool_path_reliable,
        "cex_path_positive": result.annualised_cex_path > 0,
        "cex_path_in_bounds": lo <= result.annualised_cex_path <= hi,
        "analytical_in_bounds": lo <= result.annualised_analytical <= hi,
        "same_order_of_magnitude": (
            result.annualised_analytical > 0
            and Decimal("0.1") <= result.annualised_cex_path / result.annualised_analytical <= Decimal("10")
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}
