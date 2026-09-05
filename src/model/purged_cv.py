"""Purged, embargoed cross-validation (Lopez de Prado).

Weekly targets overlap, so an ordinary K-fold leaks: a training observation
whose forward window straddles the test fold has already seen the answer. Left
alone this manufactures an R-squared that does not survive contact with
out-of-sample data.

Purge = the target horizon (7 days). Embargo >= 1 week after each test fold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class PurgedKFold:
    """K-fold with purging and an embargo, scikit-learn compatible.

    Parameters
    ----------
    n_splits
        Number of folds.
    purge_days
        Training observations whose target window overlaps the test fold are
        dropped. Equals the target horizon.
    embargo_days
        Additional gap after each test fold, to break residual serial
        correlation that purging alone does not remove.
    """

    def __init__(self, n_splits: int = 5, purge_days: int = 7, embargo_days: int = 7):
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(self, X: pd.DataFrame, y=None, groups=None):
        raise NotImplementedError("Stage 6.2")

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits


def verify_no_overlap(splits, timestamps: pd.Series, horizon_days: int) -> None:
    """Assert no training target window overlaps its test fold. Test, not trust."""
    raise NotImplementedError("Stage 6.2")
