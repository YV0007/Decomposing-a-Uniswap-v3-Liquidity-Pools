"""Figure style and savers. Every figure in the deck is produced by a script.

No figure is hand-edited. `save_figure` stamps the generating script and a hash
of the config into the file's metadata, so any figure in the deck can be traced
back to the code and configuration that made it — which is what makes the
reproducibility claim checkable rather than asserted.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")            # headless; scripts must not need a display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402
import pandas as pd              # noqa: E402

#: Consistent styling across the deck and the companion GEX paper.
STYLE = {
    "figure.figsize": (7.0, 4.2),
    "figure.dpi": 160,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
    "legend.frameon": False,
}

#: Fee tiers get consistent colours everywhere they appear.
TIER_COLOURS = {5: "#1f77b4", 30: "#d62728", 100: "#2ca02c"}
COST_COLOUR, INCOME_COLOUR, NET_COLOUR = "#d62728", "#2ca02c", "#333333"


def apply_style() -> None:
    plt.rcParams.update(STYLE)


def _config_hash() -> str:
    from src.utils.config import CONFIG_PATH

    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()[:12]


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def save_figure(fig, name: str, script: str, subdir: str = "") -> Path:
    """Save to `outputs/figures/`, stamping provenance into the metadata."""
    from src.utils.config import REPO_ROOT

    out = REPO_ROOT / "outputs" / "figures" / subdir
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{name}.png"
    fig.savefig(
        dest,
        metadata={
            "Software": f"script={script} git={_git_revision()} config={_config_hash()}",
            "Creation Time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    plt.close(fig)
    return dest


# --------------------------------------------------------------------------- #
# The deck's figures
# --------------------------------------------------------------------------- #

def decomposition_waterfall(row: pd.Series, title: str = ""):
    """Output 1 as a waterfall: advertised APR down to realised net.

    The visual point is that the bar starts at the number an LP is shown and
    ends somewhere they were never shown. Costs are drawn in one colour and
    income in another, so the reader can see at a glance that the largest step
    is range management rather than adverse selection — which is the honest
    version of the claim.
    """
    apply_style()
    steps = [
        ("Advertised\nAPR", float(row["advertised_apr"]), "start"),
        ("Range\nmanagement", -abs(float(row["range_management_cost"])), "cost"),
        ("Concentration", float(row["concentration_effect"]), "either"),
        ("LVR", -abs(float(row["lvr"])), "cost"),
        ("MEV", -abs(float(row.get("mev", 0.0))), "cost"),
        ("Gas", -abs(float(row["gas"])), "cost"),
        ("Realised\nnet", float(row["net"]), "end"),
    ]
    fig, ax = plt.subplots()
    running = 0.0
    for i, (label, value, kind) in enumerate(steps):
        if kind in ("start", "end"):
            ax.bar(i, value, color=NET_COLOUR, width=0.62)
            running = value
        else:
            colour = COST_COLOUR if value < 0 else INCOME_COLOUR
            ax.bar(i, value, bottom=running, color=colour, width=0.62, alpha=0.85)
            running += value
        ax.text(i, running + (0.004 if value >= 0 else -0.010),
                f"{value:+.1%}", ha="center", fontsize=7.5)
    ax.axhline(0, color="#888", linewidth=0.8)
    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps], fontsize=8)
    ax.set_ylabel("annualised return")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    if title:
        ax.set_title(title, fontsize=10)
    return fig


def lvr_theory_vs_empirical(empirical: pd.Series, analytical: pd.Series, fit=None):
    """H3: empirical LVR against analytical, with the 45-degree line and the fit.

    Gets its own slide regardless of outcome — the gap between the two series is
    the finding, not a failure of it. The 45-degree line is drawn because the
    prediction is beta = 1, so the eye should be able to judge the claim without
    reading the regression table.
    """
    apply_style()
    fig, ax = plt.subplots()
    ax.scatter(analytical, empirical, s=9, alpha=0.35, edgecolor="none", color=TIER_COLOURS[30])
    lim = max(float(analytical.max()), float(empirical.max()))
    ax.plot([0, lim], [0, lim], "--", color="#888", linewidth=1, label="45°  (β = 1)")
    if fit is not None:
        xs = pd.Series([0, lim])
        ax.plot(xs, fit.alpha + fit.beta * xs, color=COST_COLOUR, linewidth=1.4,
                label=f"fit: β = {fit.beta:.2f} ± {1.96 * fit.beta_se:.2f}")
    ax.set_xlabel("analytical LVR  (σ²-based)")
    ax.set_ylabel("empirical LVR")
    ax.legend(fontsize=8)
    return fig


def range_width_sweep(sweep: pd.DataFrame, predicted_delta: float | None = None):
    """Stage 8: net return against range width, with the predicted optimum.

    Fees and LVR are drawn together so the reader can see they move as one — the
    result that concentration is sign-neutral is visible in the picture rather
    than only in the table.
    """
    apply_style()
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(7.0, 5.6),
                                   gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(sweep["realised_delta"], sweep["fees"], "o-", color=INCOME_COLOUR,
             label="fees", markersize=4)
    ax1.plot(sweep["realised_delta"], -sweep["lvr"].abs(), "o-", color=COST_COLOUR,
             label="−LVR", markersize=4)
    ax1.set_xscale("log")
    ax1.set_ylabel("annualised")
    ax1.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax1.legend(fontsize=8)

    ax2.plot(sweep["realised_delta"], sweep["net"], "o-", color=NET_COLOUR, markersize=4)
    ax2.axhline(0, color="#888", linewidth=0.8)
    if predicted_delta:
        ax2.axvline(predicted_delta, color=TIER_COLOURS[5], linestyle=":", linewidth=1.4,
                    label=f"predicted δ* = {predicted_delta:.3f}")
        ax2.legend(fontsize=8)
    ax2.set_xscale("log")
    ax2.set_xlabel("range half-width δ  (log price)")
    ax2.set_ylabel("net")
    ax2.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    return fig


def hedge_error_by_frequency(sweep: pd.DataFrame):
    """Open question 7: hedging error against rebalance frequency."""
    apply_style()
    fig, ax = plt.subplots()
    ax.bar(sweep["freq_label"], sweep["mean_abs_error_usd"], color=COST_COLOUR, alpha=0.85,
           width=0.55)
    ax.set_ylabel("mean unhedged exposure (USD)")
    ax.set_xlabel("rebalance frequency")
    for i, v in enumerate(sweep["mean_abs_error_usd"]):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=8)
    return fig


def profitability_vs_volatility(decomp: pd.DataFrame, vol: pd.DataFrame):
    """The paper's central chart: net return against volatility.

    Each pool is one point, and both sides of the decomposition are drawn,
    because the point of the top panel is that they are *near-parallel*: fee
    income rises with variance almost as steeply as LVR does, since volume rises
    with volatility. Net is the small gap between them, which is why the bottom
    panel is noisy and why the crossover is not well determined.

    An earlier version of this figure asserted that LVR scales with variance
    while fee income does not, and shaded a narrow band labelled "crossover
    bracketed here". Both were wrong: the regression puts the crossover at 43.5%
    with a 95% interval of [32.2%, 76.2%], so the interval is drawn instead.
    """
    apply_style()
    d = decomp.merge(vol, left_on="pool", right_index=True)
    d = d[d.pool != "ETH_USDC_100bp"].sort_values("median_sigma")

    fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(7.0, 5.8),
                                 gridspec_kw={"height_ratios": [1.4, 1]})
    a1.plot(d.median_sigma, d.fees, "o--", color=INCOME_COLOUR, label="fees",
            markersize=6, linewidth=1.2, alpha=0.85)
    a1.plot(d.median_sigma, d.lvr, "o--", color=COST_COLOUR, label="LVR",
            markersize=6, linewidth=1.2, alpha=0.85)
    a1.set_ylabel("annualised, as a share of notional")
    a1.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    a1.legend(fontsize=8)
    a1.set_title("Both sides scale with variance, and nearly in parallel",
                  fontsize=10)

    a2.axhline(0, color="#888", linewidth=0.9)
    colours = [INCOME_COLOUR if v > 0 else COST_COLOUR for v in d.net_market_making]
    a2.scatter(d.median_sigma, d.net_market_making, s=70, color=colours, zorder=3)
    # Dashed, because it is an interpolation between four measured pools and not
    # a fitted curve. The crossing is bracketed between 28% and 52%, not located
    # at the point where this line happens to meet zero.
    a2.plot(d.median_sigma, d.net_market_making, "--", color=NET_COLOUR, linewidth=1,
            alpha=0.5, zorder=2)
    # The 95% interval for the crossover from the pooled pool-month regression,
    # not the gap between adjacent pools: six points cannot bracket anything.
    lo, hi, star = 0.3217, 0.7624, 0.4350
    a2.axvspan(lo, hi, color="#bbbbbb", alpha=0.16, zorder=1)
    a2.axvline(star, color="#777777", linestyle=":", linewidth=1, zorder=2)
    a2.text(star, d.net_market_making.min() * 0.62,
            "σ* = 43.5%\n95% CI [32%, 76%]", ha="center", fontsize=7.2,
            color="#555555")
    for _, r in d.iterrows():
        a2.annotate(r["pool"].replace("_", " "), (r.median_sigma, r.net_market_making),
                    textcoords="offset points", xytext=(6, 6), fontsize=7.5)
    a2.set_xlabel("median annualised volatility")
    a2.set_ylabel("net return")
    a2.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    a2.yaxis.set_major_formatter(lambda v, _: f"{v:+.0%}")
    a2.set_title("Net return does not order the pools by volatility", fontsize=10)
    fig.tight_layout()
    return fig


def h3_cross_section(cs: pd.DataFrame):
    """H3 across every pool: where the closed form holds and where it stops."""
    apply_style()
    d = cs.sort_values("median_sigma")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.6))

    a1.errorbar(d.median_sigma, d.beta, yerr=1.96 * d.se, fmt="o", capsize=4,
                markersize=6, color=NET_COLOUR)
    a1.axhline(1.0, color=COST_COLOUR, linestyle="--", linewidth=1.2, label="prediction β = 1")
    a1.set_xscale("log")
    a1.set_xlabel("median annualised volatility")
    a1.set_ylabel("β")
    a1.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    a1.legend(fontsize=7.5)
    a1.set_title("slope", fontsize=9)

    a2.plot(d.median_sigma, d.r2, "o-", color=NET_COLOUR, markersize=6)
    a2.set_xscale("log")
    a2.set_xlabel("median annualised volatility")
    a2.set_ylabel("R²")
    a2.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    a2.set_ylim(-0.03, 0.75)
    a2.set_title("explanatory power collapses at the peg", fontsize=9)
    fig.suptitle("σ²/8 has a measured domain of validity", fontsize=10)
    fig.tight_layout()
    return fig


def allocation_ladder(regimes: pd.DataFrame):
    """Four-pool allocation: the ceiling, the static rule, and the model."""
    apply_style()
    keep = regimes[~regimes.strategy.str.contains("FORCED — passive", na=False)].copy()
    keep = keep.sort_values("ann_return")
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    colours = []
    for name, v in zip(keep.strategy, keep.ann_return):
        if "oracle" in name.lower():
            colours.append("#888888")
        else:
            colours.append(INCOME_COLOUR if v > 0 else COST_COLOUR)
    y = np.arange(len(keep))
    ax.barh(y, keep.ann_return, color=colours, alpha=0.88)
    ax.set_yticks(y)
    ax.set_yticklabels([s.replace(" — ", ": ")[:46] for s in keep.strategy], fontsize=7.5)
    ax.axvline(0, color="#888", linewidth=0.9)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0%}")
    ax.set_xlabel("annualised return")
    ax.set_title("A static rule beats the model; grey bars are perfect foresight",
                 fontsize=10)
    for i, v in enumerate(keep.ann_return):
        ax.text(v, i, f"  {v:+.1%}", va="center", fontsize=7.5)
    fig.tight_layout()
    return fig


def gap_distribution(gaps_by_pool: dict[str, pd.Series], fee_bps: dict[str, int]):
    """Pool-vs-CEX price gap by fee tier — the no-arbitrage band, drawn.

    Each pool's fee is marked, because the point is that the distribution is
    bounded by roughly its own fee tier.
    """
    apply_style()
    fig, ax = plt.subplots()
    for pool_id, gaps in gaps_by_pool.items():
        bps = fee_bps[pool_id]
        ax.hist(gaps * 1e4, bins=120, histtype="step", density=True,
                color=TIER_COLOURS.get(bps, "#666"), label=f"{pool_id} ({bps}bp)")
        ax.axvline(bps, color=TIER_COLOURS.get(bps, "#666"), linestyle=":", linewidth=1)
        ax.axvline(-bps, color=TIER_COLOURS.get(bps, "#666"), linestyle=":", linewidth=1)
    ax.set_xlabel("pool − CEX price gap (bp);  dotted lines mark each pool's fee")
    ax.set_ylabel("density")
    ax.legend(fontsize=8)
    return fig
