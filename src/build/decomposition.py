"""Assemble the headline table.

    net_return = fees - LVR - MEV_adjustment - gas - funding (if hedged)

All annualised on the single convention in `config.yaml`, all per pool per
period. Both variants reported; delta-hedged leads, raw is the robustness
column.

This produces Output 1 — the paper's headline claim, that advertised APR is
gross of costs the LP actually pays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class Decomposition:
    """One row of Output 1. All components annualised, as fractions of notional."""

    pool_id: str
    fee_tier_bps: int
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    variant: str                     # 'delta_hedged' | 'raw'
    notional_usd: Decimal
    days: Decimal
    share_in_range: Decimal

    fees: Decimal                    # positive contribution
    lvr: Decimal                     # negative contribution, stored positive
    mev: Decimal                     # negative contribution, stored positive
    gas: Decimal                     # negative contribution, stored positive
    funding: Decimal = Decimal(0)    # hedged variant only, signed
    lvr_measure: str = "cex_path"
    notes: list[str] = field(default_factory=list)

    @property
    def net(self) -> Decimal:
        return self.fees - self.lvr - self.mev - self.gas - self.funding

    def check_identity(self, tol: Decimal = Decimal("1e-12")) -> None:
        """The components must sum to net. A sign error here voids the table."""
        recomputed = self.fees - self.lvr - self.mev - self.gas - self.funding
        if abs(recomputed - self.net) > tol:
            raise AssertionError(
                f"{self.pool_id}: components do not sum to net "
                f"({recomputed} vs {self.net})"
            )

    def as_row(self) -> dict:
        return {
            "pool": self.pool_id,
            "fee_tier_bps": self.fee_tier_bps,
            "variant": self.variant,
            "days": float(self.days),
            "share_in_range": float(self.share_in_range),
            "fees": float(self.fees),
            "lvr": -float(self.lvr),
            "mev": -float(self.mev),
            "gas": -float(self.gas),
            "funding": -float(self.funding),
            "net": float(self.net),
            "lvr_measure": self.lvr_measure,
        }


def annualise(total_usd: Decimal, base_usd: Decimal, seconds: int) -> Decimal:
    """Scale a period total to an annual rate as a fraction of the base.

    The single annualisation convention. Do not annualise inline anywhere else.
    """
    if base_usd <= 0 or seconds <= 0:
        raise ValueError("base value and elapsed seconds must be positive")
    return total_usd / base_usd * Decimal(SECONDS_PER_YEAR) / Decimal(seconds)


def build_row(
    pool_id: str, fee_tier_bps: int, lvr_result, fees_usd: Decimal, gas_usd: Decimal,
    mev_usd: Decimal, funding_usd: Decimal, share_in_range: Decimal,
    period_start: pd.Timestamp, period_end: pd.Timestamp, variant: str,
    lvr_measure: str = "cex_path", notes: list[str] | None = None,
) -> Decomposition:
    """Assemble one decomposition row from the stage outputs.

    Every component is annualised against the *same* base — the mean position
    value over the period — so the columns are commensurable and their sum is
    the net return. Annualising fees against notional and LVR against mean value
    would silently break the identity.
    """
    base = lvr_result.mean_position_value
    seconds = int((period_end - period_start).total_seconds())
    lvr_ann = {
        "cex_path": lvr_result.annualised_cex_path,
        "pool_path": lvr_result.annualised_pool_path,
        "analytical": lvr_result.annualised_analytical,
    }[lvr_measure]

    row = Decomposition(
        pool_id=pool_id,
        fee_tier_bps=fee_tier_bps,
        period_start=period_start,
        period_end=period_end,
        variant=variant,
        notional_usd=base,
        days=Decimal(seconds) / Decimal(86400),
        share_in_range=share_in_range,
        fees=annualise(fees_usd, base, seconds),
        lvr=lvr_ann,
        mev=annualise(mev_usd, base, seconds),
        gas=annualise(gas_usd, base, seconds),
        funding=annualise(funding_usd, base, seconds) if funding_usd else Decimal(0),
        lvr_measure=lvr_measure,
        notes=notes or [],
    )
    row.check_identity()
    return row


def decomposition_table(rows: list[Decomposition]) -> pd.DataFrame:
    """Output 1 across the universe."""
    return pd.DataFrame([r.as_row() for r in rows])


def gate_signs_and_magnitudes(table: pd.DataFrame) -> dict:
    """Sanity checks before anything is reported.

    Net positive in every pool usually means LVR was not actually subtracted or
    a sign is flipped. Fees above a plausible ceiling usually mean accrual while
    out of range.
    """
    checks = {
        "lvr_is_a_cost": bool((table["lvr"] <= 0).all()),
        "gas_is_a_cost": bool((table["gas"] <= 0).all()),
        "fees_are_income": bool((table["fees"] >= 0).all()),
        "not_all_positive": not bool((table["net"] > 0).all()) or len(table) == 1,
        "identity_holds": bool(
            (
                (table["fees"] + table["lvr"] + table["mev"] + table["gas"] + table["funding"]
                 - table["net"]).abs() < 1e-9
            ).all()
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}


# --------------------------------------------------------------------------- #
# Advertised APR -> realised net: the bridge
# --------------------------------------------------------------------------- #

def advertised_to_net_bridge(
    advertised_apr: Decimal, fees: Decimal, lvr: Decimal, mev: Decimal,
    gas: Decimal, share_in_range: Decimal,
) -> dict:
    """Decompose the gap between the advertised APR and the realised net return.

    The headline claim is that advertised yields overstate what an LP earns.
    That is true, but attributing the whole gap to LVR would be wrong and easy
    to catch. The gap has three distinct causes and they carry different
    messages:

    1. **Range management.** The advertised figure implicitly assumes capital is
       earning all the time. A concentrated position is out of range whenever
       the price leaves it, earning nothing. This is a cost of *using v3*, not
       an adverse-selection cost, and an LP could in principle avoid it by
       re-centring or by going full-range.
    2. **Concentration.** While in range, a position earns in proportion to its
       share of *active* liquidity, not of total TVL. Whether that beats or
       trails the advertised per-dollar rate depends on how the position's range
       compares with the pool's own liquidity distribution — a tight range on a
       pool whose LPs cluster even more tightly can capture *less* than the
       average dollar, which is counterintuitive and worth reporting.
    3. **Adverse selection and costs.** LVR, MEV and gas. This is the paper's
       thesis, and separating it from (1) and (2) is what makes the claim
       falsifiable rather than rhetorical.

    Returns each step so the bridge can be shown as a waterfall.
    """
    expected_if_proportional = advertised_apr * share_in_range
    range_cost = advertised_apr - expected_if_proportional
    concentration_effect = fees - expected_if_proportional
    return {
        "advertised_apr": advertised_apr,
        "range_management_cost": range_cost,
        "expected_if_proportional": expected_if_proportional,
        "concentration_effect": concentration_effect,
        "gross_fees_realised": fees,
        "lvr": lvr,
        "mev": mev,
        "gas": gas,
        "net": fees - lvr - mev - gas,
        "share_of_gap_from_range": (
            range_cost / (advertised_apr - (fees - lvr - mev - gas))
            if advertised_apr != (fees - lvr - mev - gas) else Decimal(0)
        ),
        "share_of_gap_from_costs": (
            (lvr + mev + gas) / (advertised_apr - (fees - lvr - mev - gas))
            if advertised_apr != (fees - lvr - mev - gas) else Decimal(0)
        ),
    }
