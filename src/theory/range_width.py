"""Optimal v3 range width — the original mathematics.

Promoted from appendix to something close to the main event by the Stage 5
bridge, which found that range management, not adverse selection, accounts for
70-78% of the gap between advertised APR and realised net return.

The model
---------
Work in log price `x = log S`, where the price is a driftless Brownian motion
with annualised volatility `sigma`. A position occupies a symmetric band of
half-width `delta` and is **re-centred whenever the price leaves it**, so it is
always in range and the cost of concentration appears as re-centring gas rather
than as idle time. That matches the baseline position spec in `DECISIONS.md` 0.2.

Three rates, each per unit of position value per unit time.

**Fees.** A position's liquidity per dollar goes as `1/delta`: from
`V = L*sqrt(P)*delta` for a narrow band, `L = V/(sqrt(P)*delta)`. Fee income is
proportional to `L`, so

    fee_rate(delta) = F / delta,    F = volume_rate * f / (sqrt(P) * L_active)

`F` is measurable from pool data and is calibrated, not assumed.

**LVR.** From `l = (sigma^2/2) * S^2 * |dn/dS|` with the v3 amount function,
`l = sigma^2 * L * sqrt(P) / 4`, so per unit value

    lvr_rate(delta) = sigma^2 / (4 * delta)

Validated against the implementation on ETH/USDC 30bp, January 2023: measured
20.81% per year in range against a predicted 20.13%, a 3.4% gap.

**Re-centring.** Exit time from a symmetric band under driftless Brownian motion
has `E[tau] = delta^2 / sigma^2`, so exits arrive at rate `sigma^2 / delta^2`.
With gas `g` per re-centre on a position of value `V`,

    recentre_rate(delta) = (g / V) * sigma^2 / delta^2

Two constraints the naive model omits
-------------------------------------
Left alone, `net(delta) = kappa/delta - A sigma^2/delta^2` diverges: fees and
LVR both scale as `1/delta`, so when `kappa > 0` the net income term grows
without bound as the range narrows and only re-centring cost stops it. Calibrated
on ETH/USDC 30bp that produced an "optimum" of +/-0.2% paying 364% a year, which
is the model failing, not a finding.

**Fee saturation.** A position's fee share is `L / (L_active + L)`, not
`L / L_active`. As it concentrates, its own liquidity enters the denominator and
its share saturates at 1 rather than growing without limit:

    fee_rate(delta) = (R / V) * beta / (delta + beta)

with `beta = delta_obs * (L_pos / L_active)` measured at any observed width, and
`R/V` the pool's whole fee revenue per unit of position value. For
`delta >> beta` this collapses to `F / delta`, recovering the linear model.

**The tick grid.** A range cannot be narrower than one tick spacing.

Which binds first is a question about position size, and it answers open
question 4. For a $100k position on ETH/USDC 30bp: saturation sets in at
`beta = 2.95e-4` (2.95 bp) while the tick floor sits at 0.602% — **twenty times
larger**. So the tick grid binds and capacity does not, until the position
reaches roughly **$2m** on this pool. Below that the linear model is sound and
the closed form applies; above it the saturating form is required.

The result
----------
    net(delta) = kappa / delta  -  A * sigma^2 / delta^2
    kappa = F - sigma^2 / 4,     A = g / V

Two things follow, and the first is the more interesting.

**1. Concentration is sign-neutral.** Fees and LVR both scale as `1/delta`, so
narrowing a range amplifies income and adverse selection *identically*. Choosing
a tighter range cannot turn an unprofitable position profitable, and cannot turn
a profitable one unprofitable. Whether liquidity provision pays at all is
decided entirely by

    kappa > 0   <=>   F > sigma^2 / 4

and not at all by how the LP chooses to concentrate. Range width sets only the
*scale* of the outcome and the re-centring bill.

**2. Given `kappa > 0`, there is an interior optimum with a closed form.**

    delta* = 2 * A * sigma^2 / kappa
    net*   = kappa^2 / (4 * A * sigma^2)

The second derivative at `delta*` is `-kappa / delta*^3 < 0`, so it is a
maximum. The comparative statics are readable: the optimal range widens with
gas and with volatility, and narrows as the fee margin improves.

When `kappa <= 0` there is no interior optimum. `net(delta)` is negative for
every finite width and rises toward zero as `delta -> infinity`, so the least-bad
concentrated position is the widest one — which is the model's way of saying
"do not provide liquidity here".

The realisable optimum is `max(delta*, delta_min)`, since `net` is increasing on
`(0, delta*)` and a range below the tick floor cannot be held. When the floor
binds, the LP is at a corner: the pool's own granularity, not the economics, is
setting the position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RangeWidthSolution:
    """Solution to the range-width problem, with the diagnosis when there is none."""

    kappa: float                  # F - sigma^2/4, the net fee margin coefficient
    optimal_half_width: float | None   # delta*, unconstrained; None when kappa <= 0
    optimal_net_rate: float | None     # net* per unit value per year
    profitable: bool
    fee_coefficient: float
    sigma: float
    gas_over_value: float
    note: str
    realisable_half_width: float | None = None   # after the tick-grid floor
    realisable_net_rate: float | None = None
    binding_constraint: str = "interior"          # interior | tick_grid | none


def fee_rate(delta: float, fee_coefficient: float) -> float:
    """Fee income per unit value per year, linear model. `F / delta`.

    Valid while the position is small enough not to dilute its own fee share —
    below roughly $2m on ETH/USDC 30bp. Above that use
    :func:`fee_rate_saturating`.
    """
    _require_positive(delta, "delta")
    return fee_coefficient / delta


def fee_rate_saturating(delta: float, pool_revenue_over_value: float, beta: float) -> float:
    """Fee income with the position's own liquidity in the denominator.

    `(R/V) * beta / (delta + beta)`. Bounded above by `R/V` — a position cannot
    earn more than the whole pool's fee revenue however tightly it concentrates.
    """
    _require_positive(delta, "delta")
    _require_positive(beta, "beta")
    return pool_revenue_over_value * beta / (delta + beta)


def tick_spacing_half_width(tick_spacing: int) -> float:
    """Smallest realisable log half-width on a pool's tick grid."""
    return math.log(1.0001**tick_spacing)


def saturation_half_width(observed_delta: float, liquidity_share: float) -> float:
    """`beta`: the width below which a position starts diluting its own fee share.

    `beta = delta * (L_pos / L_active)`, and since `L_pos = V / (sqrt(P) delta)`
    the delta cancels — `beta = V / (sqrt(P) L_active)` is a property of the
    position's *size* relative to the pool, not of the width it happens to be
    measured at.

    Taking the observed liquidity share at an observed width avoids having to
    express `sqrt(P) * L_active` in USD, which is a unit conversion easy to get
    wrong and impossible to notice afterwards.

    Answers open question 4. Compare against :func:`tick_spacing_half_width`:
    whichever is larger is the binding floor. Measured on ETH/USDC 30bp, a $100k
    position holds 0.29% of active liquidity at a +/-10% range, giving
    `beta = 2.95e-4` against a 60-tick floor of `6.0e-3` — so the grid binds by a
    factor of twenty, and capacity does not bind until roughly $2m.
    """
    _require_positive(observed_delta, "observed_delta")
    _require_positive(liquidity_share, "liquidity_share")
    return observed_delta * liquidity_share


def capacity_limit_usd(
    position_value: float, observed_delta: float, liquidity_share: float, tick_spacing: int
) -> float:
    """Position size at which fee saturation starts to bind before the tick grid.

    `beta` is linear in position size, so the capacity limit is the size that
    lifts it to the tick floor.
    """
    beta = saturation_half_width(observed_delta, liquidity_share)
    return position_value * tick_spacing_half_width(tick_spacing) / beta


def lvr_rate(delta: float, sigma: float) -> float:
    """LVR per unit value per year. `sigma^2 / (4 delta)`."""
    _require_positive(delta, "delta")
    return sigma**2 / (4 * delta)


def recentre_rate(delta: float, sigma: float, gas_over_value: float) -> float:
    """Re-centring cost per unit value per year. `(g/V) sigma^2 / delta^2`.

    Exits from a symmetric band arrive at rate `sigma^2 / delta^2`, which is why
    a very narrow range is expensive to hold even when it is profitable to hold.
    """
    _require_positive(delta, "delta")
    return gas_over_value * sigma**2 / delta**2


def net_rate(delta: float, fee_coefficient: float, sigma: float, gas_over_value: float) -> float:
    """Net return per unit value per year at half-width `delta`."""
    return (
        fee_rate(delta, fee_coefficient)
        - lvr_rate(delta, sigma)
        - recentre_rate(delta, sigma, gas_over_value)
    )


def kappa(fee_coefficient: float, sigma: float) -> float:
    """`F - sigma^2/4`. Positive iff liquidity provision pays at *any* width."""
    return fee_coefficient - sigma**2 / 4


def optimal_half_width(
    fee_coefficient: float, sigma: float, gas_over_value: float,
    tick_spacing: int | None = None,
) -> RangeWidthSolution:
    """Closed-form solution `delta* = 2 A sigma^2 / kappa`, clipped to the tick grid.

    `net` is increasing on `(0, delta*)`, so when the unconstrained optimum falls
    below what the tick grid can express the LP sits at a corner and the pool's
    granularity, not the economics, sets the position.
    """
    _require_positive(sigma, "sigma")
    _require_positive(gas_over_value, "gas_over_value")
    k = kappa(fee_coefficient, sigma)

    if k <= 0:
        return RangeWidthSolution(
            kappa=k, optimal_half_width=None, optimal_net_rate=None, profitable=False,
            fee_coefficient=fee_coefficient, sigma=sigma, gas_over_value=gas_over_value,
            binding_constraint="none",
            note=(
                f"F = {fee_coefficient:.5f} does not cover sigma^2/4 = "
                f"{sigma**2 / 4:.5f}. Fees and LVR both scale as 1/delta, so no "
                f"choice of range width makes this profitable; the position loses "
                f"at every concentration and the loss shrinks toward zero only as "
                f"the range widens."
            ),
        )

    d_star = 2 * gas_over_value * sigma**2 / k
    net_star = k**2 / (4 * gas_over_value * sigma**2)

    floor = tick_spacing_half_width(tick_spacing) if tick_spacing else 0.0
    if floor > d_star:
        realisable, binding = floor, "tick_grid"
        realisable_net = net_rate(floor, fee_coefficient, sigma, gas_over_value)
        note = (
            f"unconstrained optimum {d_star:.5f} is below the tick grid's "
            f"{floor:.5f}; the LP is at a corner and the pool's granularity sets "
            f"the position"
        )
    else:
        realisable, binding, realisable_net = d_star, "interior", net_star
        note = f"interior maximum; second derivative -kappa/delta^3 = {-k / d_star**3:.4g} < 0"

    return RangeWidthSolution(
        kappa=k, optimal_half_width=d_star, optimal_net_rate=net_star,
        profitable=True, fee_coefficient=fee_coefficient, sigma=sigma,
        gas_over_value=gas_over_value, note=note,
        realisable_half_width=realisable, realisable_net_rate=realisable_net,
        binding_constraint=binding,
    )


def optimal_half_width_numerical(
    fee_coefficient: float, sigma: float, gas_over_value: float,
    lo: float = 1e-4, hi: float = 5.0, n: int = 200_000,
) -> tuple[float, float]:
    """Grid search, as an independent check on the closed form.

    A derivation and its own implementation can be wrong together; a grid search
    over the same objective cannot make the same algebra mistake.
    """
    best_d, best_v = lo, -math.inf
    step = (hi - lo) / n
    for i in range(n + 1):
        d = lo + i * step
        v = net_rate(d, fee_coefficient, sigma, gas_over_value)
        if v > best_v:
            best_d, best_v = d, v
    return best_d, best_v


def calibrate_fee_coefficient(in_range_fee_rate: float, delta: float) -> float:
    """Recover `F` from an observed in-range fee rate at a known half-width.

    `F = fee_rate * delta`. Calibrated from data rather than assumed, so the
    optimisation is anchored to the pool it is solved for.
    """
    _require_positive(delta, "delta")
    return in_range_fee_rate * delta


def half_width_from_prices(low: float, high: float) -> float:
    """Log half-width of a realised range, measured about its geometric centre.

    Realised ranges are snapped to the tick grid and are not symmetric in
    arithmetic price, so the width that enters the model must be measured from
    the bounds rather than taken from the request.
    """
    if not 0 < low < high:
        raise ValueError(f"need 0 < low < high, got {low} and {high}")
    return math.log(high / math.sqrt(low * high))


def _require_positive(x: float, name: str) -> None:
    if not x > 0:
        raise ValueError(f"{name} must be positive, got {x}")
