"""Figure style and savers. Every figure in the deck is produced by a script.

No figure is hand-edited. `save_figure` writes the generating script name and
the config hash into the file metadata so any figure in the deck can be traced
back to the code and configuration that made it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

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


def apply_style() -> None:
    plt.rcParams.update(STYLE)


def save_figure(fig, name: str, script: str, subdir: str = "") -> Path:
    """Save to `outputs/figures/`, stamping provenance into the metadata."""
    raise NotImplementedError("Stage 5+")


def decomposition_waterfall(decomposition, pool_id: str):
    """Output 1 as a waterfall: advertised APR -> fees -> LVR -> MEV -> gas -> net.

    The headline figure of the paper. The visual point is that the bar starts
    at the advertised number and ends somewhere the LP was never shown.
    """
    raise NotImplementedError("Stage 5.1 — slide 7")


def lvr_theory_vs_empirical_scatter(empirical, analytical, fit):
    """H3: empirical LVR against analytical, with the 45-degree line and the fit.

    Slide 8. Gets its own slide regardless of outcome — the gap between the two
    series is the finding, not a failure of it.
    """
    raise NotImplementedError("Stage 3.3 — slide 8")
