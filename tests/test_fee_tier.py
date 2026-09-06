"""Fee tier and the no-arbitrage band — open question 5.

The load-bearing test is that the simulation recovers the frictionless LVR rate
as the fee goes to zero. If it did not, the headline result — that a fee band
does *not* reduce gross LVR — would be an artefact of the simulator rather than
a property of the process.
"""

from __future__ import annotations

import math

import pytest

from src.theory.fee_tier import (net_rate_for_tier, optimal_fee_tier,
                                 simulate_fee_band, uninformed_volume)

FAST = {"n_paths": 3, "steps_per_year": 365 * 24 * 12}


def test_frictionless_limit_recovers_the_closed_form():
    """With no fee the simulation must reproduce sigma^2 / (4 delta)."""
    r = simulate_fee_band(0.60, 0.0, half_width=0.10, **FAST)
    assert r.lvr_vs_frictionless == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize("fee", [0.0005, 0.003, 0.01])
def test_a_fee_band_does_not_reduce_gross_lvr(fee):
    """The central result, and it contradicts H4's stated premise.

    For a driftless walk reflected on [-f, f], local time accumulates at
    sigma^2 / (2f) across both boundaries, and each unit of local time
    transfers (L sqrt(P) / 2) * f. The f cancels: a wider band makes arbitrage
    rarer and each event proportionally larger, exactly offsetting.

    Confirmed on real pools: LVR per unit variance is 0.00553, 0.00576 and
    0.00590 for the 5bp, 30bp and 100bp pools — a 20x fee range moving the
    slope 6.7%, with t = +0.30.
    """
    r = simulate_fee_band(0.60, fee, half_width=0.10, **FAST)
    assert r.lvr_vs_frictionless == pytest.approx(1.0, abs=0.08)


def test_a_wider_band_means_rarer_arbitrage():
    """The frequency does fall — it is the per-event size that compensates."""
    tight = simulate_fee_band(0.60, 0.0005, **FAST)
    wide = simulate_fee_band(0.60, 0.01, **FAST)
    assert wide.n_arb_events_per_year < tight.n_arb_events_per_year / 4


def test_lvr_scales_with_variance_not_volatility():
    a = simulate_fee_band(0.30, 0.003, **FAST)
    b = simulate_fee_band(0.60, 0.003, **FAST)
    assert b.lvr_rate / a.lvr_rate == pytest.approx(4.0, rel=0.15)


def test_concentration_amplifies_the_simulated_rate():
    wide = simulate_fee_band(0.60, 0.003, half_width=0.40, **FAST)
    narrow = simulate_fee_band(0.60, 0.003, half_width=0.05, **FAST)
    assert narrow.lvr_rate > wide.lvr_rate * 4


def test_volume_elasticity_is_an_assumption_not_a_result():
    """Doubling the fee must reduce uninformed volume by the stated elasticity."""
    v = uninformed_volume(0.006, 0.003, 100.0, elasticity=1.0)
    assert v == pytest.approx(50.0)
    assert uninformed_volume(0.003, 0.003, 100.0, elasticity=2.0) == pytest.approx(100.0)


def test_optimal_tier_follows_the_volume_elasticity():
    """With no LVR benefit from a wider band, the tier choice is decided
    entirely by fee income — so the answer tracks the elasticity assumption."""
    tiers = (0.0005, 0.003, 0.01)
    inelastic = optimal_fee_tier(0.60, tiers, 0.003, 50.0, elasticity=0.2, **FAST)
    elastic = optimal_fee_tier(0.60, tiers, 0.003, 50.0, elasticity=2.0, **FAST)
    assert inelastic["best_fee"] >= elastic["best_fee"]


def test_net_rate_reports_both_flows():
    r = net_rate_for_tier(0.003, 0.60, 0.003, 50.0, elasticity=1.0, **FAST)
    assert r["arb_volume"] > 0 and r["uninformed_volume"] > 0
    assert r["net"] == pytest.approx(r["fee_income"] - r["lvr"])


def test_degenerate_inputs_are_rejected():
    with pytest.raises(ValueError):
        simulate_fee_band(0.0, 0.003)
    with pytest.raises(ValueError):
        uninformed_volume(0.0, 0.003, 100.0, 1.0)
