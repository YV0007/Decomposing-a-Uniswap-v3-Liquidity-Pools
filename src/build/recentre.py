"""Simulation of a re-centred LP position.

The baseline position spec re-centres on range exit, and the range-width theory
assumes it — the whole point of that model is that concentration's cost appears
as re-centring gas rather than as idle time out of range. Validating the theory
against data therefore needs a simulation that actually re-centres.

Each segment runs from an entry until the price leaves the range. At that point
the position is burned, fees are collected, gas is paid for burn + collect +
mint, and a fresh position is opened centred on the prevailing price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from src.build.fees import accrue_fees_approach_b, fees_to_usd
from src.build.lvr import analytical_lvr_rate, lvr_from_cex_path
from src.build.position import (Position, open_position, range_state, RangeState,
                                risky_delta)
from src.utils.config import PoolSpec

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class RecentredResult:
    """Totals over a re-centred position's life, all annualised as fractions."""

    half_width: Decimal
    realised_half_width_log: float
    n_recentres: int
    days: Decimal
    mean_value_usd: Decimal
    fees: Decimal
    lvr_cex_path: Decimal
    lvr_analytical: Decimal
    gas: Decimal
    share_in_range: Decimal
    #: Per-block risky-asset delta across the whole life, including re-centrings.
    #: The hedge tracks this, not the delta of any single position.
    delta_path: pd.DataFrame | None = None
    #: Median share of active liquidity the position held. Above a few percent
    #: the position is not a price-taker and the simulation's assumptions fail —
    #: $100k is 0.09% of ETH/USDC 5bp but 22.6% of the 100bp pool.
    median_liquidity_share: float = 0.0

    @property
    def net(self) -> Decimal:
        return self.fees - self.lvr_cex_path - self.gas

    @property
    def net_analytical(self) -> Decimal:
        return self.fees - self.lvr_analytical - self.gas


def _realised_log_half_width(pos: Position, spec: PoolSpec) -> float:
    import math

    from src.utils import precision as pr

    a = float(pr.tick_to_price(pos.tick_lower, spec.token0.decimals,
                               spec.token1.decimals, spec.invert_price))
    b = float(pr.tick_to_price(pos.tick_upper, spec.token0.decimals,
                               spec.token1.decimals, spec.invert_price))
    lo, hi = min(a, b), max(a, b)
    return math.log(hi / math.sqrt(lo * hi))


def simulate_recentred(
    aligned: pd.DataFrame, swaps: pd.DataFrame, spec: PoolSpec,
    notional_usd: Decimal, half_width: Decimal, vol: pd.Series,
    gas_per_recentre_usd: Decimal, gas_entry_exit_usd: Decimal,
) -> RecentredResult:
    """Run a position that re-centres whenever the price leaves its range.

    `aligned` carries block state and the CEX reference; `swaps` is the raw swap
    log used for fee replay. Both must cover the same blocks.

    Notional is held constant across re-centrings rather than compounded, so the
    comparison across widths is like for like: a width that happens to have done
    well early would otherwise be handed a larger base for the rest of the run.
    """
    if aligned.empty:
        raise ValueError("no aligned blocks to simulate")

    blocks = aligned.reset_index(drop=True)
    swaps_by_block = swaps.set_index("block_number", drop=False).sort_index()

    delta_rows: list[dict] = []
    liq_shares: list[float] = []
    total_fees = Decimal(0)
    total_lvr_cex = Decimal(0)
    total_lvr_ana = Decimal(0)
    n_recentres = 0
    in_range_seconds = 0
    values: list[Decimal] = []
    widths: list[float] = []

    i = 0
    n = len(blocks)
    while i < n:
        entry = blocks.iloc[i]
        pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                            Decimal(str(entry.price)), notional_usd, half_width)
        widths.append(_realised_log_half_width(pos, spec))

        # Walk forward to the first block outside the range.
        j = i + 1
        while j < n and range_state(pos, int(blocks.iloc[j].tick)) is RangeState.IN_RANGE:
            j += 1
        seg_end = min(j, n - 1)

        seg = blocks.iloc[i : seg_end + 1]
        seg_seconds = int(seg.iloc[-1].block_timestamp) - int(seg.iloc[0].block_timestamp)
        in_range_seconds += max(0, seg_seconds)

        # Fees over the segment, replayed from the swap log.
        lo_b, hi_b = int(seg.iloc[0].block_number), int(seg.iloc[-1].block_number)
        seg_swaps = swaps_by_block.loc[
            (swaps_by_block.index > lo_b) & (swaps_by_block.index <= hi_b)
        ]
        if len(seg_swaps):
            acc = accrue_fees_approach_b(seg_swaps, pos, spec, entry_tick=int(entry.tick))
            total_fees += fees_to_usd(int(acc.fee0.sum()), int(acc.fee1.sum()),
                                      spec, Decimal(str(seg.iloc[-1].price)))

        # LVR over the segment.
        prev_cex = None
        for cex_p, ts, sig in zip(seg["cex_price"], seg["block_timestamp"], vol.iloc[i : seg_end + 1]):
            if cex_p is None or pd.isna(sig):
                continue
            c_now = Decimal(str(cex_p))
            if prev_cex is not None:
                total_lvr_cex += lvr_from_cex_path(pos, spec, prev_cex, c_now)
            prev_cex = c_now
        seg_years = Decimal(max(0, seg_seconds)) / Decimal(SECONDS_PER_YEAR)
        mid = seg.iloc[len(seg) // 2]
        if not pd.isna(vol.iloc[i + len(seg) // 2]):
            sigma = Decimal(str(vol.iloc[i + len(seg) // 2])).sqrt()
            total_lvr_ana += analytical_lvr_rate(pos, spec, Decimal(str(mid.cex_price)), sigma) * seg_years
        for blk, ts, sq in zip(seg["block_number"], seg["block_timestamp"], seg["sqrt_price_x96"]):
            delta_rows.append({
                "block_number": int(blk), "block_timestamp": int(ts),
                "sqrt_price_x96": int(sq),
                "risky_delta": risky_delta(pos, int(sq), spec),
            })
        seg_liq = [int(v) for v in seg.get("liquidity", pd.Series(dtype=object)) ] if "liquidity" in seg else []
        liq_shares.extend(pos.liquidity / L for L in seg_liq if L > 0)
        values.append(notional_usd)

        if seg_end >= n - 1:
            break
        n_recentres += 1
        i = seg_end

    span = int(blocks.iloc[-1].block_timestamp) - int(blocks.iloc[0].block_timestamp)
    gas_total = gas_entry_exit_usd + Decimal(n_recentres) * gas_per_recentre_usd
    base = notional_usd

    def ann(x: Decimal) -> Decimal:
        return x / base * Decimal(SECONDS_PER_YEAR) / Decimal(max(1, span))

    return RecentredResult(
        half_width=half_width,
        realised_half_width_log=sum(widths) / len(widths),
        n_recentres=n_recentres,
        days=Decimal(span) / Decimal(86400),
        mean_value_usd=base,
        fees=ann(total_fees),
        lvr_cex_path=ann(total_lvr_cex),
        lvr_analytical=ann(total_lvr_ana),
        gas=ann(gas_total),
        share_in_range=Decimal(in_range_seconds) / Decimal(max(1, span)),
        delta_path=pd.DataFrame(delta_rows).drop_duplicates("block_number", keep="last"),
        median_liquidity_share=float(pd.Series(liq_shares).median()) if liq_shares else 0.0,
    )
