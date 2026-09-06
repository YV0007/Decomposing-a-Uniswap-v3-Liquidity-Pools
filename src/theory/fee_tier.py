"""Optimal fee tier as a function of volatility — open question 5.

The mechanism H4 rests on: arbitrage only fires once the price gap clears the
fee, so a higher tier is a wider no-arbitrage band and less LVR per unit of
volatility — bought at the price of less uninformed volume.

The derivation
--------------
Write everything in log price. Let `g = log(S/P)` be the gap between the
external price `S` and the pool price `P`.

The LP's value, marked at the external price, is `V(P; S) = x(P) S + y(P)`, and
the AMM invariant gives `y'(P) = -P x'(P)`, so

    dV/dP = x'(P) (S - P)

For a v3 position, `x'(P) = -L / (2 P^{3/2})`, and for a small gap
`S - P ≈ P g`. Substituting with `dP = P dp`:

    dLVR = (L sqrt(P) / 2) g dp

An arbitrageur facing fee `f` trades only while the gap exceeds `f`, and stops
exactly when it reaches `f`. Integrating along that trade, from a gap `g` down
to `f`:

    LVR per arbitrage event = (L sqrt(P) / 4) (g² - f²)          [1]

**The frictionless limit checks out.** With `f = 0` and continuous monitoring
the gap reaches `sigma sqrt(dt)` in each interval, so
`dLVR = (L sqrt(P)/4) sigma² dt` — exactly the `sigma² L sqrt(P) / 4` that
`src.build.lvr.analytical_lvr_rate` computes, and hence `sigma² V / 8` for a
full-range pool. `tests/test_fee_tier.py` asserts this.

Equation [1] is what makes the fee band tractable: the gap is a random walk
reflected at `±f`, and every reflection transfers `(L sqrt(P)/4)(g² - f²)`.
A larger `f` means rarer reflections, and the `- f²` term means each one
transfers less than it would without the fee.

What is *not* derived here is the volume response. How much uninformed flow a
pool loses when its fee rises is an empirical elasticity, not a theorem, and it
is carried as an explicit parameter with the result's sensitivity to it shown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FeeTierResult:
    """Simulated economics of one fee tier at one volatility."""

    fee: float
    sigma: float
    lvr_rate: float            # per unit position value per year
    arb_volume_rate: float     # per unit position value per year
    n_arb_events_per_year: float
    lvr_vs_frictionless: float  # ratio to sigma^2/(4 delta)


def simulate_fee_band(
    sigma: float, fee: float, half_width: float = 0.10,
    years: float = 1.0, steps_per_year: int = 365 * 24 * 12,   # 5-minute steps
    n_paths: int = 24, seed: int = 42,
) -> FeeTierResult:
    """Monte-Carlo the gap process and accumulate LVR from equation [1].

    The gap is a driftless random walk reflected at `±fee`: it drifts with the
    external price and is knocked back to the boundary each time an arbitrageur
    fires. Every reflection transfers `(L sqrt(P)/4)(g² - f²)`.

    Returned rates are per unit of position value, so they are directly
    comparable to `sigma²/(4 delta)` and to the measured LVR in the
    decomposition.
    """
    if fee < 0 or sigma <= 0 or half_width <= 0:
        raise ValueError("sigma and half_width must be positive; fee non-negative")

    n_steps = max(1, int(steps_per_year * years))
    dt = years / n_steps
    step_sd = sigma * math.sqrt(dt)
    rng = np.random.default_rng(seed)

    # Position value V = L sqrt(P) delta, so (L sqrt(P)/4) = V / (4 delta).
    # Working per unit of V, the coefficient is 1/(4 delta).
    coef = 1.0 / (4.0 * half_width)

    lvr_total = 0.0
    vol_total = 0.0
    events = 0
    for _ in range(n_paths):
        shocks = rng.normal(0.0, step_sd, n_steps)
        gap = 0.0
        for eps in shocks:
            gap += eps
            if gap > fee:
                lvr_total += coef * (gap * gap - fee * fee)
                vol_total += (gap - fee) / (2.0 * half_width)
                events += 1
                gap = fee
            elif gap < -fee:
                lvr_total += coef * (gap * gap - fee * fee)
                vol_total += (-gap - fee) / (2.0 * half_width)
                events += 1
                gap = -fee

    return FeeTierResult(
        fee=fee, sigma=sigma,
        lvr_rate=lvr_total / n_paths / years,
        arb_volume_rate=vol_total / n_paths / years,
        n_arb_events_per_year=events / n_paths / years,
        lvr_vs_frictionless=(lvr_total / n_paths / years) / (sigma**2 / (4 * half_width)),
    )


def lvr_reduction_factor(sigma: float, fee: float, **kw) -> float:
    """How much of frictionless LVR survives a fee band of width `fee`.

    1.0 means the fee buys no protection; 0.0 means complete protection.
    """
    return simulate_fee_band(sigma, fee, **kw).lvr_vs_frictionless


def uninformed_volume(fee: float, base_fee: float, base_volume: float,
                      elasticity: float) -> float:
    """Uninformed flow as a function of the fee, with constant elasticity.

    `volume(f) = base_volume * (f / base_fee) ** (-elasticity)`.

    **This is an assumption, not a result.** The elasticity is the weakest link
    in the whole fee-tier question and the answer is sensitive to it, so it is a
    parameter and the sensitivity is reported rather than a number being quietly
    chosen.
    """
    if fee <= 0 or base_fee <= 0:
        raise ValueError("fees must be positive")
    return base_volume * (fee / base_fee) ** (-elasticity)


def net_rate_for_tier(
    fee: float, sigma: float, base_fee: float, base_uninformed_volume: float,
    elasticity: float, half_width: float = 0.10, **kw,
) -> dict:
    """Net return per unit position value per year at one fee tier.

    Fee income comes from both flows and LVR only from the arbitrage side:

        net = fee * (uninformed_volume + arb_volume) - LVR
    """
    sim = simulate_fee_band(sigma, fee, half_width=half_width, **kw)
    uninformed = uninformed_volume(fee, base_fee, base_uninformed_volume, elasticity)
    fee_income = fee * (uninformed + sim.arb_volume_rate)
    return {
        "fee": fee, "sigma": sigma,
        "uninformed_volume": uninformed,
        "arb_volume": sim.arb_volume_rate,
        "fee_income": fee_income,
        "lvr": sim.lvr_rate,
        "lvr_vs_frictionless": sim.lvr_vs_frictionless,
        "net": fee_income - sim.lvr_rate,
        "n_arb_events": sim.n_arb_events_per_year,
    }


def optimal_fee_tier(
    sigma: float, tiers: tuple[float, ...], base_fee: float,
    base_uninformed_volume: float, elasticity: float, half_width: float = 0.10, **kw,
) -> dict:
    """Best available tier at a given volatility, and the whole curve."""
    rows = [net_rate_for_tier(f, sigma, base_fee, base_uninformed_volume,
                              elasticity, half_width, **kw) for f in tiers]
    best = max(rows, key=lambda r: r["net"])
    return {"sigma": sigma, "best_fee": best["fee"], "best_net": best["net"], "curve": rows}
