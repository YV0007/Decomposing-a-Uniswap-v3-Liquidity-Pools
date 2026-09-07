"""Stage 5 across the full sample — the headline decomposition.

Three returns, kept distinct (see `src.build.recentre`):

- `net_market_making` = fees − LVR − gas. **Already delta-hedged**, because LVR
  is defined against a continuously rebalanced portfolio. The headline.
- `net_hedged_implemented` = that, less real perp funding and trading costs.
  What an LP could actually achieve with a purchasable hedge.
- `total_return` = value change + fees − gas. The unhedged position, directional
  beta intact.

They satisfy `total = rebalanced + market_making`, asserted per cohort.

One monthly cohort per pool per month: open a $100k position at +/-10%, re-centre
on range exit, hold to month end. Both variants reported — delta-hedged leads,
raw is the robustness column.

Monthly cohorts matter. A single entry date makes the headline an artefact of
that date: a position opened 1 January 2023 was run over by a 40% rally in its
second week, and one opened three weeks later was not.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months, load_derived, month_bounds
from src.build.hedge import simulate_hedge_legs
from src.build.recentre import simulate_recentred
from src.fetch.binance_data import load_funding_rates, load_perp_klines_1m
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pools
from src.utils.speclog import log_specification
from src.utils.stats import block_bootstrap_ci

NOTIONAL, HALF_WIDTH = Decimal("100000"), Decimal("0.10")
GAS_RECENTRE = GAS_ENTRY_EXIT = Decimal("22.39")
HEDGE_FREQ = 3600          # hourly, per the revised Stage 0.1 baseline


def run_cohort(spec, year: int, month: int, bounds: dict) -> dict | None:
    k0 = f"{year:04d}-{month:02d}"
    ky, km = (year + 1, 1) if month == 12 else (year, month + 1)
    k1 = f"{ky:04d}-{km:02d}"
    if k0 not in bounds or k1 not in bounds:
        return None

    d = load_derived(spec, [(year, month)])
    if len(d) < 50:
        return None
    sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))

    r = simulate_recentred(d, sw, spec, NOTIONAL, HALF_WIDTH, d["rv_annualised"],
                           GAS_RECENTRE, GAS_ENTRY_EXIT)

    row = {
        "pool": spec.id, "fee_tier_bps": spec.fee_tier_bps, "year": year, "month": month,
        "days": float(r.days), "n_recentres": r.n_recentres,
        "share_in_range": float(r.share_in_range),
        "realised_delta": r.realised_half_width_log,
        "median_liquidity_share": r.median_liquidity_share,
        "fees": float(r.fees), "lvr": float(r.lvr_cex_path),
        "lvr_analytical": float(r.lvr_analytical), "gas": float(r.gas),
        "net_market_making": float(r.net_market_making),
        "rebalanced_return": float(r.rebalanced_return),
        "total_return": float(r.total_return),
        "median_liquidity_share": r.median_liquidity_share,
    }
    r.check_identity()

    legs = spec.hedge_map
    if not legs:
        # A stable/stable pool carries no USD price risk, so the market-making
        # return already *is* the hedged return. Reporting a hedge here would be
        # reporting the cost of a trade with nothing to offset.
        row.update({"funding": 0.0, "hedge_trading_cost": 0.0, "hedge_pnl": 0.0,
                    "hedge_error_usd": 0.0,
                    "net_hedged_implemented": float(r.net_market_making),
                    "hedge_note": "no USD price risk; nothing to hedge"})
        return row
    try:
        perps = {sym: load_perp_klines_1m(sym, year, month) for sym in set(legs.values())}
        funds = {sym: load_funding_rates(sym, year, month) for sym in set(legs.values())}
        h = simulate_hedge_legs(r.delta_path, spec, perps, funds, HEDGE_FREQ,
                                base_usd=NOTIONAL)
        row.update({
            "funding": float(h.funding), "hedge_trading_cost": float(h.trading_cost),
            "hedge_pnl": float(h.pnl),
            "hedge_error_usd": float(h.mean_abs_error_usd),
            "net_hedged_implemented": float(r.net_market_making) - float(h.funding)
                                      - float(h.trading_cost),
            "hedge_note": f"{len(legs)}-leg",
        })
    except Exception as exc:
        row.update({"funding": None, "hedge_trading_cost": None, "hedge_pnl": None,
                    "hedge_error_usd": None, "net_hedged_implemented": None,
                    "hedge_note": f"{type(exc).__name__}: {str(exc)[:60]}"})
    return row


def main() -> int:
    bounds = month_bounds()
    rows = []
    for spec in pools("all"):
        months = available_months(spec)
        print(f"\n=== {spec.id}: {len(months)} cohorts ===", flush=True)
        for y, m in months:
            try:
                r = run_cohort(spec, y, m, bounds)
                if r:
                    rows.append(r)
                    print(f"  {y}-{m:02d}  in-range {r['share_in_range']:5.1%}  "
                          f"fees {r['fees']:+8.2%}  lvr {r['lvr']:+8.2%}  "
                          f"mkt-making {r['net_market_making']:+8.2%}  "
                          f"total {r['total_return']:+9.2%}",
                          flush=True)
            except Exception as exc:
                print(f"  {y}-{m:02d}: FAILED {type(exc).__name__} {str(exc)[:70]}", flush=True)

    t = pd.DataFrame(rows)
    out = REPO_ROOT / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "cohorts_fullsample_all.csv", index=False)

    log_specification(
        stage="5", component="decomposition_fullsample",
        params={"notional": float(NOTIONAL), "half_width": float(HALF_WIDTH),
                "recentre": "on_range_exit", "hedge_freq_s": HEDGE_FREQ,
                "cohorts": "monthly"},
        metric_name="n_cohorts", metric_value=len(t),
        notes="full-sample Stage 5, both variants",
    )

    print("\n\n=== Output 1: full sample, monthly cohorts, $100k at +/-10% ===\n")
    agg = []
    for pid, g in t.groupby("pool", sort=False):
        row = {"pool": pid, "fee_tier_bps": int(g.fee_tier_bps.iloc[0]), "n_cohorts": len(g)}
        for col in ("share_in_range", "fees", "lvr", "gas", "net_market_making",
                    "rebalanced_return", "total_return"):
            row[col] = g[col].mean()
        hg = g.dropna(subset=["net_hedged_implemented"])
        row["funding"] = hg["funding"].mean() if len(hg) else float("nan")
        row["net_hedged_implemented"] = (hg["net_hedged_implemented"].mean()
                                         if len(hg) else float("nan"))
        for col, key in (("net_market_making", "mm_ci"),
                         ("total_return", "total_ci")):
            try:
                lo, hi = block_bootstrap_ci(g[col], block_size=6, n_boot=2000)
                row[key] = f"[{lo:+.1%}, {hi:+.1%}]"
            except Exception:
                row[key] = "n/a"
        row["share_of_months_positive"] = float((g["net_market_making"] > 0).mean())
        agg.append(row)

    a = pd.DataFrame(agg)
    show = a.copy()
    for c in ("share_in_range", "fees", "lvr", "gas", "net_market_making",
              "rebalanced_return", "total_return", "funding",
              "net_hedged_implemented", "share_of_months_positive"):
        show[c] = show[c].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "n/a")
    print(show.to_string(index=False))
    a.to_csv(out / "decomposition_fullsample_all.csv", index=False)
    print(f"\nwrote decomposition_fullsample_all.csv and cohorts_fullsample_all.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
