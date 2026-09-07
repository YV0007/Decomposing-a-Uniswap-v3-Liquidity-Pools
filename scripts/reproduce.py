"""Run the whole pipeline in order and check every gate.

The reproducibility standard is that any figure or table can be regenerated
from the repository plus the config. This is the entry point that does it, and
it is also the thing to run after any change: a stage that quietly stops
matching its gate should fail here rather than in a slide.

    python3 scripts/reproduce.py            # verify what is already built
    python3 scripts/reproduce.py --full     # rebuild everything from raw data

Stages are ordered by dependency and a failed gate stops the run, because a
number computed on top of a broken stage is worse than no number.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config import REPO_ROOT

#: (script, description, needs raw data rebuild, is a hard gate)
PIPELINE = [
    ("verify_pools.py", "Stage 1.1 — pool addresses, token order, decimals", False, True),
    ("stage1_pool_state.py", "Stage 1 — price reconstruction gate", False, True),
    ("stage1b_alignment.py", "Stage 1.3 — CEX alignment, causality", False, True),
    ("stage2_fees.py", "Stage 2 — fee accrual vs feeGrowthInside", False, True),
    ("stage3_lvr.py", "Stage 3 — LVR sanity gate", False, True),
    ("fetch_all.py", "fetch swaps and CEX klines", True, False),
    ("fetch_hedge_inputs.py", "fetch perp prices, funding, DVOL", True, False),
    ("build_derived.py", "build the derived layer", True, False),
    ("stage5_fullsample.py", "Stage 5 — decomposition, full sample", True, False),
    ("h3_regression.py", "H3 — the closed form against observed LVR", True, False),
    ("build_panel.py", "weekly forecast panel", True, False),
    ("stage6_h5_h6.py", "H5 and H6 — forecasting and the horse race", True, False),
    ("stage7_backtest.py", "H7 — allocation strategy", True, False),
    ("stage8_range_width.py", "Stage 8 — optimal range width", True, False),
    ("build_extension_pools.py", "fetch and build WBTC/ETH and USDC/USDT", True, False),
    ("cross_section.py", "cross-section — does sigma^2/8 generalise?", True, False),
    ("allocation_regimes.py", "allocation — flexible vs forced, four pools", True, False),
    ("robustness_subperiods_q2.py", "robustness — subperiods, regimes, Q2", True, False),
    ("robustness_position.py", "robustness — range width, hedge frequency", True, False),
    ("robustness_mev.py", "robustness — MEV classification rules", True, False),
    ("robustness_alignment.py", "robustness — block/CEX alignment", True, False),
    ("make_figures.py", "regenerate every figure", False, False),
    ("audit_deck.py", "audit — every deck number against its table", False, True),
]


def run(script: str, timeout: int = 7200) -> tuple[bool, float, str]:
    path = REPO_ROOT / "scripts" / script
    if not path.exists():
        return False, 0.0, "script missing"
    t0 = time.time()
    env = {"PYTHONPATH": str(REPO_ROOT)}
    try:
        r = subprocess.run(
            [sys.executable, str(path)], capture_output=True, text=True,
            timeout=timeout, cwd=REPO_ROOT,
            env={**dict(__import__("os").environ), **env},
        )
        tail = (r.stdout or r.stderr).strip().split("\n")[-1][:90]
        return r.returncode == 0, time.time() - t0, tail
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, f"timed out after {timeout}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="rebuild from raw data (hours); default verifies what exists")
    ap.add_argument("--stop-on-fail", action="store_true", default=True)
    args = ap.parse_args()

    print("=" * 88)
    print(f"REPRODUCE — {'full rebuild' if args.full else 'verify existing outputs'}")
    print("=" * 88)

    print("\n--- test suite ---")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       capture_output=True, text=True, cwd=REPO_ROOT,
                       env={**dict(__import__("os").environ), "PYTHONPATH": str(REPO_ROOT)})
    line = [l for l in r.stdout.split("\n") if "passed" in l or "failed" in l]
    print(f"  {line[-1] if line else 'no result'}")
    if r.returncode != 0:
        print("\nTESTS FAILED — stopping. A pipeline standing on failing tests proves nothing.")
        return 1

    failures = []
    for script, desc, needs_raw, is_gate in PIPELINE:
        if needs_raw and not args.full:
            print(f"\n--- SKIP  {desc}")
            print(f"          ({script}; needs --full)")
            continue
        print(f"\n--- RUN   {desc}")
        ok, secs, tail = run(script)
        mark = "PASS" if ok else ("GATE FAILED" if is_gate else "FAILED")
        print(f"    {mark:12s} {secs:7.1f}s  {script}")
        if tail:
            print(f"    {tail}")
        if not ok:
            failures.append((script, is_gate))
            if is_gate and args.stop_on_fail:
                print(f"\nHARD GATE FAILED at {script}. Stopping — diagnose, do not proceed.")
                return 1

    print("\n" + "=" * 88)
    if failures:
        print(f"{len(failures)} stage(s) failed:")
        for s, g in failures:
            print(f"  {'GATE ' if g else ''}{s}")
        return 1
    print("All stages and gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
