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
from src.utils.plotting import (allocation_ladder, apply_style, COST_COLOUR,
                                h3_cross_section, INCOME_COLOUR, NET_COLOUR,
                                TIER_COLOURS, decomposition_waterfall,
                                gap_distribution, hedge_error_by_frequency,
                                lvr_theory_vs_empirical,
                                profitability_vs_volatility, range_width_sweep,
                                save_figure)

T = REPO_ROOT / "outputs" / "tables"
SCRIPT = "make_figures.py"


def read(name):
    p = T / name
    return pd.read_csv(p) if p.exists() else None


def fig_crossover():
    """Slide 7 — the central chart: net return against volatility."""
    dec = read("decomposition_fullsample_all.csv")
    vol = read("cross_section_volatility.csv")
    if dec is None or vol is None:
        return None
    return profitability_vs_volatility(dec, vol.set_index("pool"))


def fig_h3_cross():
    """Slide 8 — H3 across the whole cross-section."""
    cs = read("cross_section_h3.csv")
    return None if cs is None else h3_cross_section(cs)


def fig_allocation():
    """Slide 13 — the four-pool allocation ladder."""
    r = read("allocation_regimes.csv")
    return None if r is None else allocation_ladder(r)


def fig_h3_scatter():
    """Slide 8 — H3. Analytical against empirical LVR, with the 45-degree line."""
    xs = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
    d = pd.read_parquet(xs if xs.exists()
                        else REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
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
    xs = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
    d = pd.read_parquet(xs if xs.exists()
                        else REPO_ROOT / "data" / "processed" / "h3_daily.parquet")
    d = d[d.pool != "USDC_USDT_1bp"]      # LVR there is not variance-driven
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


def fig_lvr_bias_by_sigma():
    """Step 4 — the closed form's domain of validity, in one chart.

    The single most useful theoretical result the project has: sigma^2/8 does
    not simply work or fail, it under-predicts below roughly 0.6 annualised
    volatility, is unbiased between about 0.6 and 0.9, and over-predicts above.
    Both previously separate failures - the peg and the extreme days - are the
    two ends of this curve.
    """
    t = read("lvr_bias_by_sigma.csv")
    if t is None:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    x, y = t["median_sigma"].to_numpy(), t["agg_ratio"].to_numpy()
    ax.axhline(1.0, color="0.35", lw=1, ls="--", zorder=1)
    ax.plot(x, y, "-o", color=NET_COLOUR, lw=2, ms=7, zorder=3)
    for xi, yi, n in zip(x, y, t["n"]):
        ax.annotate(f"{yi:.2f}", (xi, yi), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=8)
    ax.axhspan(0.95, 1.05, color=NET_COLOUR, alpha=0.10, zorder=0)
    ax.set_xscale("log")
    ax.set_xlabel("annualised volatility (log scale)")
    ax.set_ylabel("realised LVR / closed form")
    ax.set_title("Where $\\sigma^2/8$ holds: under-predicts calm, over-predicts extreme")
    ax.annotate("adverse-selection floor\n(the peg)", (x[0], y[0]),
                textcoords="offset points", xytext=(26, -6), fontsize=8, color="0.3")
    ax.annotate("over-predicts\n(top 1% of days)", (x[-1], y[-1]),
                textcoords="offset points", xytext=(-30, -34), ha="center",
                fontsize=8, color="0.3")
    ax.margins(y=0.16)
    fig.tight_layout()
    return fig


def fig_static_rule():
    """Step 3 — the rule against cash, and down the volatility ladder."""
    t = read("static_rule.csv")
    if t is None:
        return None
    rf = t[t.test == "risk_free_sensitivity"]
    ld = t[t.test == "rank_ladder"]
    if rf.empty or ld.empty:
        return None
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.0))

    a1.axhline(0, color="0.35", lw=1)
    a1.plot(rf["rf"] * 100, rf["excess_ann"] * 100, "-o",
            color=NET_COLOUR, lw=2, ms=7)
    a1.set_xlabel("assumed cash rate (%)")
    a1.set_ylabel("excess return (% a year)")
    a1.set_title("Against cash, the rule earns nothing")
    for _, r in rf.iterrows():
        a1.annotate(f"p={r['deflated_prob']:.2f}", (r["rf"] * 100, r["excess_ann"] * 100),
                    textcoords="offset points", xytext=(6, 6), fontsize=8, color="0.3")

    cols = [INCOME_COLOUR if v > 0 else COST_COLOUR for v in ld["ann"]]
    a2.bar(ld["rank"].astype(int), ld["ann"] * 100, color=cols, width=0.62)
    a2.axhline(0, color="0.35", lw=1)
    # The pool name goes on the axis, not in the bar: the shorter bars cannot
    # hold it, and outside the bar it collides with the title.
    a2.set_xticks(ld["rank"].astype(int))
    a2.set_xticklabels([f"{int(r['rank'])}\n{str(r['modal_pool']).replace('_', ' ')}"
                        for _, r in ld.iterrows()], fontsize=8)
    a2.set_xlabel("rank by lagged volatility (1 = lowest)")
    a2.set_ylabel("return (% a year)")
    a2.set_title("Not a volatility rule: rank 2 loses money")
    for _, r in ld.iterrows():
        up = r["ann"] > 0
        a2.annotate(f"{r['ann'] * 100:+.1f}%", (int(r["rank"]), r["ann"] * 100),
                    textcoords="offset points", xytext=(0, 4 if up else -12),
                    ha="center", fontsize=8, color="0.25")
    a2.margins(y=0.14)
    fig.tight_layout()
    return fig


def main() -> int:
    made = []
    fig, fit = fig_h3_scatter()
    made.append(save_figure(fig, "h3_theory_vs_empirical", SCRIPT))
    print(f"  H3 scatter: beta {fit.beta:.3f}, R2 {fit.r_squared:.3f}")

    for name, fn in (("crossover_profitability", fig_crossover),
                     ("h3_cross_section", fig_h3_cross),
                     ("allocation_ladder", fig_allocation),
                     ("h3_by_regime", fig_h3_by_regime),
                     ("fee_tier_lvr_flat", fig_fee_tier_lvr),
                     ("range_width_full_sample", fig_range_width_full),
                     ("mev_span_sensitivity", fig_mev_sensitivity),
                     ("backtest_returns", fig_backtest_curve),
                     ("lvr_bias_by_sigma", fig_lvr_bias_by_sigma),
                     ("static_rule", fig_static_rule)):
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
