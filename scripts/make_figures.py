"""Regenerate every figure in the deck from the output tables.

No figure is hand-edited and none is produced outside this script, so the deck
is reproducible from the repository alone. Each file carries the git revision
and a hash of `config.yaml` in its metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT
from src.utils.plotting import (apply_style, COST_COLOUR, INCOME_COLOUR, NET_COLOUR,
                                TIER_COLOURS, decomposition_waterfall,
                                gap_distribution, hedge_error_by_frequency,
                                lvr_theory_vs_empirical, range_width_sweep,
                                save_figure)

T = REPO_ROOT / "outputs" / "tables"
SCRIPT = "make_figures.py"


def read(name):
    p = T / name
    return pd.read_csv(p) if p.exists() else None


def fig_h3_scatter():
    """Slide 8 — H3. Analytical against empirical LVR, with the 45-degree line."""
    d = pd.read_parquet(REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
    d = d[d.pool.isin(("ETH_USDC_5bp", "ETH_USDC_30bp"))]
    d = d[(d.lvr_analytical_usd > 0) & d.lvr_empirical_usd.notna()]
    from src.utils.stats import newey_west_ols
    fit = newey_west_ols(d.lvr_empirical_usd, d.lvr_analytical_usd)
    return lvr_theory_vs_empirical(d.lvr_empirical_usd, d.lvr_analytical_usd, fit), fit


def fig_h3_by_regime():
    """Slide 14 — where the theory breaks, and where it does not."""
    apply_style()
    sub = read("robustness_subperiods.csv")
    reg = read("robustness_regimes.csv")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.5, 3.6))
    for ax, t, key, title in ((a1, sub, "period", "by year"),
                              (a2, reg, "period", "by volatility regime")):
        if t is None:
            continue
        x = np.arange(len(t))
        ax.errorbar(x, t["beta"], yerr=1.96 * t.get("se", pd.Series([0] * len(t))),
                    fmt="o", color=TIER_COLOURS[30], capsize=3, markersize=5)
        ax.axhline(1.0, color=COST_COLOUR, linestyle="--", linewidth=1.2,
                   label="prediction β = 1")
        ax.set_xticks(x)
        ax.set_xticklabels(t[key], rotation=0, fontsize=8)
        ax.set_ylabel("β" if ax is a1 else "")
        ax.set_title(title, fontsize=9)
        ax.legend(fontsize=7)
    fig.suptitle("H3: the level match is stable; the slope is not", fontsize=10)
    fig.tight_layout()
    return fig


def fig_fee_tier_lvr():
    """Slide 9 — LVR per unit variance is flat across a 20x fee range."""
    apply_style()
    d = pd.read_parquet(REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
    from src.utils.stats import newey_west_ols
    fig, ax = plt.subplots()
    tiers, slopes, errs = [], [], []
    for pid, g in d.groupby("pool", sort=False):
        g = g.copy()
        g["var"] = g.sigma_annual.astype(float) ** 2
        g["lvr_norm"] = g.lvr_empirical_usd / g.value_usd
        g = g[(g["var"] > 0) & g.lvr_norm.notna()]
        f = newey_west_ols(g.lvr_norm, g["var"])
        tiers.append(int(g.fee_tier_bps.iloc[0]))
        slopes.append(f.beta)
        errs.append(1.96 * f.beta_se)
    order = np.argsort(tiers)
    tiers = np.array(tiers)[order]
    slopes = np.array(slopes)[order]
    errs = np.array(errs)[order]
    ax.errorbar(tiers, slopes, yerr=errs, fmt="o-", capsize=4, markersize=6,
                color=NET_COLOUR)
    ax.set_xscale("log")
    ax.set_xticks(tiers)
    ax.set_xticklabels([f"{t}bp" for t in tiers])
    ax.set_xlabel("fee tier")
    ax.set_ylabel("LVR per unit variance")
    ax.set_ylim(0, max(slopes + errs) * 1.3)
    ax.set_title("A 20× fee range does not change LVR (t = +0.30)", fontsize=10)
    return fig


def fig_range_width_full():
    """Slide 13 — range width across the full sample."""
    apply_style()
    t = read("robustness_position.csv")
    if t is None:
        return None
    fig, ax = plt.subplots()
    for pid, g in t.groupby("pool", sort=False):
        m = g.groupby("half_width")["net_market_making" if "net_market_making" in g
                                     else "net_raw"].mean()
        bps = 5 if "5bp" in pid else 30
        ax.plot(m.index, m.values, "o-", color=TIER_COLOURS[bps], label=pid, markersize=5)
    ax.axhline(0, color="#888", linewidth=0.8)
    ax.set_xscale("log")
    ax.set_xticks(sorted(t.half_width.unique()))
    ax.set_xticklabels([f"±{w:.0%}" for w in sorted(t.half_width.unique())])
    ax.set_xlabel("range half-width")
    ax.set_ylabel("market-making return, annualised")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(fontsize=8)
    ax.set_title("Monotone in width: the corner solution Stage 8 predicts", fontsize=10)
    return fig


def fig_mev_sensitivity():
    """Slide 14 — MEV under both span measures."""
    apply_style()
    t = read("robustness_mev.csv")
    if t is None:
        return None
    fig, ax = plt.subplots()
    for meas, colour in (("pool_position", INCOME_COLOUR), ("log_index", COST_COLOUR)):
        g = t[t.rule.str.contains(meas, na=False)].copy()
        if not len(g):
            continue
        g["span"] = g.rule.str.extract(r"span (\d+)").astype(float)
        g = g.sort_values("span")
        ax.plot(g["span"], g.profit_usd / 1e6, "o-", color=colour,
                label=meas.replace("_", " "), markersize=5)
    ax.set_xscale("log")
    ax.set_xlabel("max leg span")
    ax.set_ylabel("attacker profit, $m over 43 months")
    ax.legend(fontsize=8)
    ax.set_title("Span measured in pool position converges; log_index does not",
                 fontsize=10)
    return fig


def fig_backtest_curve():
    """Slide 13 — cumulative strategy against the benchmarks."""
    apply_style()
    t = read("stage7_backtest.csv")
    if t is None:
        return None
    fig, ax = plt.subplots()
    x = np.arange(len(t))
    colours = [INCOME_COLOUR if v > 0 else COST_COLOUR for v in t.ann_return]
    ax.barh(x, t.ann_return, color=colours, alpha=0.85)
    ax.set_yticks(x)
    ax.set_yticklabels(t.strategy, fontsize=7.5)
    ax.axvline(0, color="#888", linewidth=0.8)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel("annualised return")
    ax.set_title("Every LP variant is negative; holding the tokens is not", fontsize=10)
    ax.invert_yaxis()
    return fig


def main() -> int:
    made = []
    fig, fit = fig_h3_scatter()
    made.append(save_figure(fig, "h3_theory_vs_empirical", SCRIPT))
    print(f"  H3 scatter: beta {fit.beta:.3f}, R2 {fit.r_squared:.3f}")

    for name, fn in (("h3_by_regime", fig_h3_by_regime),
                     ("fee_tier_lvr_flat", fig_fee_tier_lvr),
                     ("range_width_full_sample", fig_range_width_full),
                     ("mev_span_sensitivity", fig_mev_sensitivity),
                     ("backtest_returns", fig_backtest_curve)):
        try:
            f = fn()
            if f is not None:
                made.append(save_figure(f, name, SCRIPT))
        except Exception as exc:
            print(f"  {name}: FAILED {type(exc).__name__} {str(exc)[:70]}")

    b = read("advertised_bridge_2023-01.csv")
    if b is not None:
        for _, row in b.iterrows():
            f = decomposition_waterfall(row, f"{row['pool']} — advertised APR to realised net")
            made.append(save_figure(f, f"waterfall_{row['pool']}", SCRIPT))

    s = read("range_width_sweep_2023-01.csv")
    if s is not None:
        made.append(save_figure(range_width_sweep(s, 0.0416), "range_width_jan2023", SCRIPT))

    print(f"\n{len(made)} figures written to outputs/figures/")
    for p in made:
        print(f"  {p.name:38s} {p.stat().st_size // 1024:4d} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
