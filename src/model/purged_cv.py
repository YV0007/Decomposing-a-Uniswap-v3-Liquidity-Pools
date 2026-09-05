"""Purged, embargoed cross-validation (Lopez de Prado).

Weekly targets overlap, so an ordinary K-fold leaks: a training observation
whose forward window straddles the test fold has already seen the answer. Left
alone this manufactures an R-squared that does not survive contact with
out-of-sample data.

Two separate mechanisms, and they are not interchangeable:

**Purging** removes training observations whose *target window* overlaps the
test fold. This is the direct leak — the training label is literally computed
from data inside the test period.

**Embargo** removes a further span of training observations *after* the test
fold. This handles the indirect leak: serial correlation means an observation
just after the test fold still carries information about it, even though its
target window does not overlap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class PurgedKFold:
    """K-fold with purging and an embargo, scikit-learn compatible.

    Parameters
    ----------
    n_splits
        Number of contiguous, time-ordered test folds.
    purge_days
        Length of the target's forward window. A training observation is purged
        when `t + purge_days` reaches into the test fold. Set this equal to the
        target horizon; setting it shorter leaves a leak open.
    embargo_days
        Additional span dropped after each test fold.
    """

    def __init__(self, n_splits: int = 5, purge_days: int = 7, embargo_days: int = 7):
        if n_splits < 2:
            raise ValueError("n_splits must be at least 2")
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def split(self, X: pd.DataFrame, y=None, groups=None):
        """Yield `(train_idx, test_idx)` positional index arrays.

        `X` must carry a `DatetimeIndex`, or a `timestamp` column. Folds are
        contiguous in time — shuffling would destroy the whole point.
        """
        ts = self._timestamps(X)
        if not ts.is_monotonic_increasing:
            raise ValueError("observations must be sorted by time before splitting")

        n = len(ts)
        purge = pd.Timedelta(days=self.purge_days)
        embargo = pd.Timedelta(days=self.embargo_days)

        for lo, hi in self._fold_bounds(n):
            test_idx = np.arange(lo, hi)
            t_start, t_end = ts.iloc[lo], ts.iloc[hi - 1]

            # Purge: a training label spanning [t, t + purge] must not reach
            # into the test window at all.
            overlaps = (ts + purge >= t_start) & (ts <= t_end)
            # Embargo: drop a further span immediately after the test fold.
            embargoed = (ts > t_end) & (ts <= t_end + embargo)

            train_mask = ~(overlaps | embargoed)
            train_mask.iloc[lo:hi] = False
            train_idx = np.flatnonzero(train_mask.to_numpy())
            if len(train_idx) == 0:
                continue
            yield train_idx, test_idx

    def _fold_bounds(self, n: int) -> list[tuple[int, int]]:
        edges = np.linspace(0, n, self.n_splits + 1).astype(int)
        return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]) if b > a]

    @staticmethod
    def _timestamps(X: pd.DataFrame) -> pd.Series:
        if isinstance(X.index, pd.DatetimeIndex):
            return pd.Series(X.index, index=range(len(X)))
        if "timestamp" in X.columns:
            return pd.Series(pd.to_datetime(X["timestamp"]).to_numpy(), index=range(len(X)))
        raise ValueError("X needs a DatetimeIndex or a 'timestamp' column")


def verify_no_overlap(
    splits, timestamps: pd.Series, horizon_days: int, embargo_days: int = 0
) -> dict:
    """Assert no training target window reaches into its test fold.

    Tested, not trusted: this is the check that would catch a purge implemented
    against the wrong horizon, which is the most likely way to leave a leak in
    place while believing it is closed.
    """
    ts = pd.Series(pd.to_datetime(timestamps).to_numpy())
    horizon = pd.Timedelta(days=horizon_days)
    embargo = pd.Timedelta(days=embargo_days)
    report = {"n_folds": 0, "violations": [], "min_train_size": None}

    for k, (train_idx, test_idx) in enumerate(splits):
        report["n_folds"] += 1
        t_start, t_end = ts.iloc[test_idx].min(), ts.iloc[test_idx].max()
        tr = ts.iloc[train_idx]
        leaks = int(((tr + horizon >= t_start) & (tr <= t_end)).sum())
        embargo_leaks = int(((tr > t_end) & (tr <= t_end + embargo)).sum())
        if leaks or embargo_leaks:
            report["violations"].append(
                {"fold": k, "target_window_overlaps": leaks, "inside_embargo": embargo_leaks}
            )
        size = len(train_idx)
        report["min_train_size"] = size if report["min_train_size"] is None else min(
            report["min_train_size"], size
        )
    report["passed"] = not report["violations"]
    return report
