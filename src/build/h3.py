"""H3 — daily LVR series for the theory test.

The claim: analytically computed LVR, from CEX realised volatility, tracks
empirically observed adverse selection. Regressed as

    empirical_LVR(t) = alpha + beta * analytical_LVR(t) + eps

with the prediction beta = 1, alpha = 0.

Why daily
---------
Monthly cohorts give 86 usable observations across two pools, which is too few
to say anything with a confidence interval. Per-block is the other extreme: the
empirical increments are cheap but the analytical rate needs two Decimal square
roots and a position valuation per point, and the sample is 8.6M blocks.

Daily is the natural resolution. Empirical LVR is summed from per-block
increments, so nothing is lost. The analytical rate is evaluated once per day
from that day's mean variance and the position held at midday — a
piecewise-constant approximation to a quantity that moves slowly relative to a
day, and one that costs 1,300 evaluations per pool instead of 5.6M.

Both series use the same re-centred position as Stage 5, so the regression tests
the theory against the strategy actually being measured rather than a different
one.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.build.derived import load_derived
from src.build.lvr import analytical_lvr_rate, lvr_from_cex_path, value_at_external
from src.build.position import RangeState, open_position, range_state
from src.utils.config import PoolSpec

SECONDS_PER_YEAR = 365 * 24 * 3600


def daily_lvr(
    spec: PoolSpec, year: int, month: int,
    notional: Decimal = Decimal("100000"), half_width: Decimal = Decimal("0.10"),
) -> pd.DataFrame:
    """Daily empirical and analytical LVR for one pool-month.

    The position re-centres on range exit, matching Stage 5. Days are UTC
    calendar days; a day straddling a re-centring carries both segments'
    contributions, which is correct — the LP held both.
    """
    d = load_derived(spec, [(year, month)])
    if len(d) < 50:
        raise ValueError(f"{spec.id} {year}-{month:02d}: too few blocks")

    d = d.reset_index(drop=True)
    d["day"] = pd.to_datetime(d["block_timestamp"].astype("int64"), unit="s", utc=True).dt.floor("D")

    rows: list[dict] = []
    i, n = 0, len(d)
    while i < n:
        entry = d.iloc[i]
        pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                            Decimal(str(entry.price)), notional, half_width)
        j = i + 1
        while j < n and range_state(pos, int(d.iloc[j].tick)) is RangeState.IN_RANGE:
            j += 1
        seg = d.iloc[i : min(j, n - 1) + 1]

        prev_cex = None
        for day, ts, cex_p, sq, rv in zip(
            seg["day"], seg["block_timestamp"], seg["cex_price"],
            seg["sqrt_price_x96"], seg["rv_annualised"],
        ):
            c = Decimal(str(cex_p))
            inc = Decimal(0) if prev_cex is None else lvr_from_cex_path(pos, spec, prev_cex, c)
            prev_cex = c
            rows.append({
                "day": day, "block_timestamp": int(ts), "lvr_empirical": inc,
                "cex_price": c, "sqrt_price_x96": int(sq), "rv": rv,
                "in_range": range_state(pos, int(seg["tick"].iloc[0])) is RangeState.IN_RANGE,
                "_pos_lower": pos.tick_lower, "_pos_upper": pos.tick_upper,
                "_liquidity": pos.liquidity,
            })
        if min(j, n - 1) >= n - 1:
            break
        i = min(j, n - 1)

    per_block = pd.DataFrame(rows)
    if per_block.empty:
        raise ValueError(f"{spec.id} {year}-{month:02d}: no LVR rows")

    out = []
    for day, g in per_block.groupby("day", sort=True):
        seconds = int(g["block_timestamp"].max() - g["block_timestamp"].min())
        if seconds <= 0:
            continue
        mid = g.iloc[len(g) // 2]
        rv = pd.Series(g["rv"]).astype(float).mean()
        if pd.isna(rv) or rv <= 0:
            continue
        sigma = Decimal(str(rv)).sqrt()

        from src.build.position import Position

        pos = Position(spec.id, 0, int(mid.sqrt_price_x96), int(mid._pos_lower),
                       int(mid._pos_upper), int(mid._liquidity), notional)
        value = value_at_external(pos, int(mid.sqrt_price_x96), Decimal(str(mid.cex_price)), spec)
        rate = analytical_lvr_rate(pos, spec, Decimal(str(mid.cex_price)), sigma)
        analytical = rate * Decimal(seconds) / Decimal(SECONDS_PER_YEAR)

        out.append({
            "pool": spec.id, "fee_tier_bps": spec.fee_tier_bps, "day": day,
            "seconds": seconds, "n_blocks": len(g),
            "lvr_empirical_usd": float(sum(g["lvr_empirical"], Decimal(0))),
            "lvr_analytical_usd": float(analytical),
            "sigma_annual": float(sigma),
            "value_usd": float(value),
            "share_in_range": float(g["in_range"].mean()),
        })
    return pd.DataFrame(out)
