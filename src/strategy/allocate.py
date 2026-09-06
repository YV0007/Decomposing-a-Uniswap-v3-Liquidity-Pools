"""Where to park LP capital. Not a buy/sell signal — an allocation decision.

The engine is the decomposition, not a single learner. H5 showed that pointing
gradient boosting at next week's *net* return fails: it is significantly worse
than predicting the historical mean. Predicting the two components separately
works better, because they have different mechanisms and different best models:

| Component | Model | Why | Out-of-sample R² |
|---|---|---|---|
| LVR | σ²/8 with a HAR-RV variance forecast | closed form, one parameter, cannot overfit | +0.126 |
| Fees | LightGBM on volume and liquidity features | no closed form; volume dynamics are empirical | +0.083 |

    predicted_net = predicted_fees − predicted_LVR − gas

Both arms beat their own baselines out of sample where predicting the net
directly does not. That is the argument for decomposing rather than regressing
the thing you care about.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def allocation_signal(
    predictions: pd.DataFrame, threshold: float = 0.0,
    scheme: str = "proportional", max_weight: float = 1.0,
) -> pd.DataFrame:
    """Per-pool PROVIDE/AVOID with weights, per week.

    `predictions` needs `week`, `pool`, `pred_fees`, `pred_lvr`, `pred_gas`.
    The decomposition is carried through to the signal so a reader can see *why*
    a pool is avoided, not merely that it is.

    Weights never sum above one; an all-AVOID week means holding cash, which is
    the point of the strategy given most weeks lose money.
    """
    d = predictions.copy()
    d["pred_net"] = d["pred_fees"] - d["pred_lvr"] - d["pred_gas"]
    d["signal"] = np.where(d["pred_net"] > threshold, "PROVIDE", "AVOID")

    out = []
    for week, g in d.groupby("week", sort=True):
        g = g.copy()
        qualifying = g["pred_net"] > threshold
        if not qualifying.any():
            g["weight"] = 0.0
        elif scheme == "equal":
            g["weight"] = np.where(qualifying, 1.0 / int(qualifying.sum()), 0.0)
        else:
            pos = g["pred_net"].clip(lower=0.0)
            total = float(pos.sum())
            g["weight"] = (pos / total) if total > 0 else 0.0
        g["weight"] = g["weight"].clip(upper=max_weight)
        s = float(g["weight"].sum())
        if s > 1.0:
            g["weight"] = g["weight"] / s
        out.append(g)
    return pd.concat(out, ignore_index=True)


def normalise_weights(raw: pd.Series, scheme: str = "proportional") -> pd.Series:
    """Weights summing to at most 1. An all-AVOID week means holding cash."""
    pos = raw.clip(lower=0.0)
    total = float(pos.sum())
    if total <= 0:
        return pd.Series(0.0, index=raw.index)
    if scheme == "equal":
        n = int((pos > 0).sum())
        return pd.Series(np.where(pos > 0, 1.0 / n, 0.0), index=raw.index)
    return pos / total
