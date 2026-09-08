"""Daily fee series, and the weekly panel the forecast models are fitted on.

`h3.daily_lvr` already produces daily LVR. This adds the other half — daily fee
income for the same re-centred position — so a daily net return exists, and then
aggregates to the weekly frequency the targets are defined at.

Weekly, not monthly: monthly cohorts give 86 observations across two pools,
which cannot support a gradient-boosted model or a meaningful confidence
interval. Weekly gives roughly 370, still modest, which is itself an argument
for taking the purged cross-validation seriously rather than trusting a single
split.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pandas as pd

from src.build.derived import load_derived, month_bounds
from src.build.fees import accrue_fees_approach_b, fees_to_usd
from src.build.position import RangeState, open_position, range_state
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import PoolSpec


def daily_fees(
    spec: PoolSpec, year: int, month: int,
    notional: Decimal = Decimal("100000"), half_width: Decimal = Decimal("0.10"),
) -> pd.DataFrame:
    """Daily fee income for the same re-centred position `h3.daily_lvr` uses.

    `deposited=True`: the LP's own liquidity joins the denominator, which is the
    realistic share and the one Stage 5 reports.
    """
    bounds = month_bounds()
    k0 = f"{year:04d}-{month:02d}"
    k1 = f"{year + 1:04d}-01" if month == 12 else f"{year:04d}-{month + 1:02d}"
    d = load_derived(spec, [(year, month)]).reset_index(drop=True)
    sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
    # USD price of token1, needed for any pool without a stablecoin leg.
    if "numeraire_usd" in d.columns:
        numeraire = [Decimal(str(v)) for v in d["numeraire_usd"]]
    elif spec.invert_price:
        numeraire = [Decimal(str(v)) for v in d["price"]]
    else:
        numeraire = [Decimal(1)] * len(d)

    rows = []
    i, n = 0, len(d)
    while i < n:
        entry = d.iloc[i]
        pos = open_position(spec, int(entry.block_number), int(entry.sqrt_price_x96),
                            Decimal(str(entry.price)), notional, half_width,
                            numeraire_usd=numeraire[i])
        j = i + 1
        while j < n and range_state(pos, int(d.iloc[j].tick)) is RangeState.IN_RANGE:
            j += 1
        end = min(j, n - 1)
        lo_b, hi_b = int(d.iloc[i].block_number), int(d.iloc[end].block_number)
        seg = sw[(sw.block_number > lo_b) & (sw.block_number <= hi_b)]
        if len(seg):
            acc = accrue_fees_approach_b(seg, pos, spec, entry_tick=int(entry.tick),
                                         deposited=True)
            acc["day"] = pd.to_datetime(acc["block_timestamp"].astype("int64"),
                                        unit="s", utc=True).dt.floor("D")
            px = Decimal(str(d.iloc[end].price))
            nm = numeraire[end]
            for day, g in acc.groupby("day", sort=True):
                rows.append({
                    "pool": spec.id, "day": day,
                    "fees_usd": float(fees_to_usd(int(g.fee0.sum()), int(g.fee1.sum()),
                                                  spec, px, numeraire_usd=nm)),
                    "swaps": len(g),
                })
        if end >= n - 1:
            break
        i = end

    if not rows:
        return pd.DataFrame(columns=["pool", "day", "fees_usd", "swaps"])
    out = pd.DataFrame(rows).groupby(["pool", "day"], as_index=False).sum()
    return out


def build_weekly_panel(
    daily_lvr: pd.DataFrame, daily_fee: pd.DataFrame, dvol: pd.Series | None = None,
    gas_per_recentre: float = 22.39, notional: float = 100_000.0,
) -> pd.DataFrame:
    """Merge to daily, aggregate to weekly, and attach strictly-lagged features.

    Every feature is a trailing statistic shifted one week, so a row stamped at
    week `t` contains nothing that happened during week `t`. The target is the
    *following* week's net return — the shift and the target move in opposite
    directions, which is what makes the panel forecastable rather than
    tautological.
    """
    d = daily_lvr.merge(daily_fee, on=["pool", "day"], how="left")
    d["fees_usd"] = d["fees_usd"].fillna(0.0)
    d["swaps"] = d["swaps"].fillna(0)
    d["net_usd"] = d["fees_usd"] - d["lvr_empirical_usd"]
    d = d.sort_values(["pool", "day"])

    frames = []
    for pid, g in d.groupby("pool", sort=False):
        g = g.set_index("day").sort_index()
        w = pd.DataFrame(index=g.resample("W").last().index)
        w["pool"] = pid
        w["fee_tier_bps"] = g["fee_tier_bps"].resample("W").last()

        wk_fees = g["fees_usd"].resample("W").sum()
        wk_lvr = g["lvr_empirical_usd"].resample("W").sum()
        wk_ana = g["lvr_analytical_usd"].resample("W").sum()
        wk_net = (g["net_usd"].resample("W").sum() - gas_per_recentre) / notional

        # --- features: trailing and lagged, so week t knows nothing of week t
        w["realized_vol_7d"] = g["sigma_annual"].resample("W").mean().shift(1)
        w["realized_vol_30d"] = g["sigma_annual"].resample("W").mean().rolling(4).mean().shift(1)
        w["vol_of_vol_30d"] = g["sigma_annual"].resample("W").mean().rolling(4).std().shift(1)
        w["swaps_7d"] = g["swaps"].resample("W").sum().shift(1)
        w["share_in_range_7d"] = g["share_in_range"].resample("W").mean().shift(1)
        w["value_usd"] = g["value_usd"].resample("W").last().shift(1)
        w["lvr_lag1"] = wk_lvr.shift(1)
        w["lvr_analytical_lag1"] = wk_ana.shift(1)
        w["fees_lag1"] = wk_fees.shift(1)
        w["net_lag1"] = wk_net.shift(1)
        if dvol is not None:
            iv = dvol.resample("W").last() / 100.0
            w["implied_vol"] = iv.shift(1)
            w["iv_rv_spread"] = w["implied_vol"] - w["realized_vol_30d"]

        # --- contemporaneous quantities and the forward targets
        w["lvr_usd"] = wk_lvr
        w["lvr_analytical_usd"] = wk_ana
        w["fees_usd"] = wk_fees
        w["net_return"] = wk_net
        w["target_net_next"] = wk_net.shift(-1)
        w["target_lvr_next"] = wk_lvr.shift(-1)
        frames.append(w.reset_index().rename(columns={"index": "day"}))

    out = pd.concat(frames, ignore_index=True)
    return out.rename(columns={out.columns[0]: "week"}).sort_values(["pool", "week"])


def pools_missing_from_cache(cached: pd.DataFrame | None,
                             want: Iterable[str]) -> set[str]:
    """Which pools of `want` a fee cache does not cover.

    The fee cache is keyed on nothing, so "the file exists" is not evidence it
    is current. Growing the pool universe once left it a universe behind, and
    the new pool merged into the panel with zero fees.
    """
    want = set(want)
    if cached is None or len(cached) == 0:
        return want
    return want - set(cached["pool"].unique())


def assert_every_pool_has_fees(fees: pd.DataFrame, want: Iterable[str]) -> None:
    """Raise if any pool in `want` carries no non-zero fee row.

    Zero is a valid fee for a quiet day, which is exactly why this needs its own
    check: a pool that is *entirely* zero is not quiet, it is missing, and its
    net return silently becomes -LVR. That produced a -57% annual return with
    0.0% of weeks positive and no gate fired.
    """
    want = set(want)
    if "fees_usd" not in fees.columns:
        raise ValueError("fee table has no fees_usd column")
    priced = set(fees.loc[fees["fees_usd"].fillna(0) > 0, "pool"].unique())
    starved = sorted(want - priced)
    if starved:
        raise ValueError(f"pools with no non-zero fees: {starved}")
