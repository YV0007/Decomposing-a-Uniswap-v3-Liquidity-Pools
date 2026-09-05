"""Specification log — every configuration tried, written as it is tried.

The Deflated Sharpe Ratio needs an honest count of the specifications searched.
That count is only honest if it is recorded prospectively; reconstructing it at
the end always undercounts. Every model fit, every sweep, every threshold
change appends a row here.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = [
    "timestamp_utc",
    "spec_hash",
    "stage",
    "component",
    "params_json",
    "metric_name",
    "metric_value",
    "notes",
]


def log_specification(
    stage: str,
    component: str,
    params: dict[str, Any],
    metric_name: str = "",
    metric_value: float | None = None,
    notes: str = "",
    log_path: Path | None = None,
) -> str:
    """Append one specification. Returns its hash.

    Call this at the point of *running* a specification, not at the point of
    reporting it. A specification that was run and discarded still counts
    toward the multiple-testing burden.
    """
    from src.utils.config import path as cfg_path

    target = log_path or cfg_path("specification_log")
    params_json = json.dumps(params, sort_keys=True, default=str)
    spec_hash = hashlib.sha256(
        f"{stage}|{component}|{params_json}".encode()
    ).hexdigest()[:12]

    is_new = not target.exists() or target.stat().st_size == 0
    with open(target, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "spec_hash": spec_hash,
                "stage": stage,
                "component": component,
                "params_json": params_json,
                "metric_name": metric_name,
                "metric_value": "" if metric_value is None else metric_value,
                "notes": notes,
            }
        )
    return spec_hash


def count_specifications(component: str | None = None, log_path: Path | None = None) -> int:
    """Number of distinct specifications tried — the `N` for the Deflated Sharpe."""
    from src.utils.config import path as cfg_path

    target = log_path or cfg_path("specification_log")
    if not target.exists():
        return 0
    with open(target, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if component is not None:
        rows = [r for r in rows if r["component"] == component]
    return len({r["spec_hash"] for r in rows})
