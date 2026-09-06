"""Robustness — position specification across the full sample.

Every baseline in `DECISIONS.md` 0.2 swept: range width, re-centring rule, and
hedge frequency. The question each answers is whether the headline (a re-centred
+/-10% position lost money) is a property of the pool or of the choices made
about the position.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months, load_derived, month_bounds
from src.build.hedge import simulate_hedge_on_path
from src.build.position import RangeState, open_position, range_state
from src.build.recentre import simulate_recentred
from src.fetch.binance_data import load_funding_rates, load_perp_klines_1m
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool, pools
from src.utils.speclog import log_specification
from src.utils.stats import block_bootstrap_ci

NOTIONAL = Decimal("100000")
GAS = Decimal("22.39")
WIDTHS = ["0.02", "0.05", "0.10", "0.25", "0.50"]
HEDGE_FREQS = ((3600, "1h"), (86_400, "1D"), (604_800, "7D"))
POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")


def never_recentre(d, sw, spec, notional, hw):
    """Open once at the start of the month and hold, whatever the price does."""
    e = d.iloc[0]
    pos = open_position(spec, int(e.block_number), int(e.sqrt_price_x96),
                        Decimal(str(e.price)), notional, hw)
    in_range = pd.Series([range_state(pos, int(t)) is RangeState.IN_RANGE for t in d["tick"]])
    dt = d["block_timestamp"].diff().shift(-1).fillna(0).clip(lower=0)
    span = max(1, int(d["block_timestamp"].iloc[-1] - d["block_timestamp"].iloc[0]))
    return float(dt[in_range.to_numpy()].sum()) / span


def main() -> int:
    bounds = month_bounds()
    rows = []
    for spec in [pool(p) for p in POOLS]:
        for y, m in available_months(spec):
            k0 = f"{y:04d}-{m:02d}"
            k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
            if k0 not in bounds or k1 not in bounds:
                continue
            try:
                d = load_derived(spec, [(y, m)])
                if len(d) < 50:
                    continue
                sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
                perp = load_perp_klines_1m("ETHUSDT", y, m)
                fund = load_funding_rates("ETHUSDT", y, m)
            except Exception as exc:
                print(f"  {spec.id} {k0}: {type(exc).__name__}", flush=True)
                continue

            for w in WIDTHS:
                r = simulate_recentred(d, sw, spec, NOTIONAL, Decimal(w),
                                       d["rv_annualised"], GAS, GAS)
                base = {"pool": spec.id, "year": y, "month": m, "half_width": float(w),
                        "realised_delta": r.realised_half_width_log,
                        "n_recentres": r.n_recentres,
                        "share_in_range": float(r.share_in_range),
                        "fees": float(r.fees), "lvr": float(r.lvr_cex_path),
                        "gas": float(r.gas), "net_raw": float(r.net),
                        "liq_share": r.median_liquidity_share}
                for secs, lab in HEDGE_FREQS:
                    try:
                        h = simulate_hedge_on_path(r.delta_path, perp, fund, secs,
                                                   base_usd=NOTIONAL)
                        base[f"net_hedged_{lab}"] = float(r.net) - float(h.funding) - float(h.trading_cost)
                        base[f"hedge_err_{lab}"] = float(h.mean_abs_error_usd)
                    except Exception:
                        base[f"net_hedged_{lab}"] = None
                        base[f"hedge_err_{lab}"] = None
                rows.append(base)
            print(f"  {spec.id} {k0}: {len(WIDTHS)} widths", flush=True)

    t = pd.DataFrame(rows)
    out = REPO_ROOT / "outputs" / "tables"
    t.to_csv(out / "robustness_position.csv", index=False)

    print("\n=== range width x pool, full sample (net raw, annualised) ===\n")
    piv = t.pivot_table(index="half_width", columns="pool", values="net_raw", aggfunc="mean")
    piv["realised_delta"] = t.groupby("half_width")["realised_delta"].mean()
    piv["mean_recentres"] = t.groupby("half_width")["n_recentres"].mean()
    print(piv.to_string(float_format=lambda v: f"{v:+9.2%}"))

    print("\n=== hedge frequency (net hedged, +/-10% only) ===\n")
    h = t[t.half_width == 0.10]
    hf = pd.DataFrame({
        lab: [h[f"net_hedged_{lab}"].mean(), h[f"hedge_err_{lab}"].mean()]
        for _, lab in HEDGE_FREQS}, index=["mean net hedged", "mean hedge error $"])
    print(hf.to_string(float_format=lambda v: f"{v:12.4f}"))

    print("\n=== confidence intervals on net, by width (pooled) ===\n")
    for w in sorted(t.half_width.unique()):
        g = t[t.half_width == w]["net_raw"].dropna()
        try:
            lo, hi = block_bootstrap_ci(g, block_size=6, n_boot=2000)
            print(f"  +/-{w:.0%}  mean {g.mean():+7.2%}  CI [{lo:+.2%}, {hi:+.2%}]  "
                  f"{'excludes zero' if hi < 0 or lo > 0 else 'spans zero'}")
        except Exception as exc:
            print(f"  +/-{w:.0%}: {exc}")

    log_specification(stage="R", component="position_sweep",
                      params={"widths": WIDTHS, "hedge_freqs": [f for _, f in HEDGE_FREQS]},
                      metric_name="n_rows", metric_value=len(t))
    print(f"\nwrote outputs/tables/robustness_position.csv ({len(t):,} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
