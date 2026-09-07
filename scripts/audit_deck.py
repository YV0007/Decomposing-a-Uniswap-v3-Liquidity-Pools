"""Audit — every number quoted in DECK.md against the table that produced it.

A deck drifts from its data the moment a stage is re-run. This turns that from
something noticed in review into something the test suite catches: each claim
is checked against the CSV it came from, and a mismatch fails.

Run after any stage re-run, before presenting anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.utils.config import REPO_ROOT

T = REPO_ROOT / "outputs" / "tables"


def load(name):
    p = T / name
    if not p.exists():
        raise FileNotFoundError(f"{name} missing — re-run the stage that writes it")
    return pd.read_csv(p)


def claims() -> list[tuple[str, float, float, float]]:
    """(label, value quoted in the deck, value in the table, tolerance)."""
    out = []

    # --- slide 7: the decomposition, all five pools ---------------------- #
    a = load("decomposition_fullsample_all.csv").set_index("pool")
    for pool, field, claimed in (
        ("USDC_USDT_1bp", "net_market_making", 0.0843),
        ("USDC_USDT_1bp", "fees", 0.1028),
        ("USDC_USDT_1bp", "lvr", 0.0158),
        ("USDC_USDT_1bp", "share_of_months_positive", 0.8293),
        ("WBTC_ETH_30bp", "net_market_making", 0.0071),
        ("WBTC_ETH_30bp", "fees", 0.3283),
        ("WBTC_ETH_30bp", "lvr", 0.3152),
    ):
        out.append((f"Slide 7 {pool} {field}", claimed, float(a.loc[pool, field]), 5e-4))

    # --- slide 8: H3 across the cross-section ---------------------------- #
    x = load("cross_section_h3.csv").set_index("pool")
    for pool, field, claimed in (
        ("USDC_USDT_1bp", "r2", 0.002), ("USDC_USDT_1bp", "ratio", 6.60),
        ("WBTC_ETH_30bp", "beta", 0.956), ("WBTC_ETH_30bp", "r2", 0.628),
        ("WBTC_ETH_30bp", "p_beta_eq_1", 0.644),
    ):
        out.append((f"Slide 8 {pool} {field}", claimed, float(x.loc[pool, field]), 6e-3))

    # --- slide 9: LVR per unit variance, four tiers ---------------------- #
    sl = load("cross_section_lvr_slopes.csv").set_index("pool")
    for pool, claimed in (("ETH_USDC_5bp", 0.00553), ("ETH_USDC_30bp", 0.00576),
                          ("WBTC_ETH_30bp", 0.00660), ("ETH_USDC_100bp", 0.00590)):
        out.append((f"Slide 9 {pool} slope", claimed, float(sl.loc[pool, "slope"]), 1e-5))

    # --- slide 13: the four-pool allocation ------------------------------ #
    r = load("allocation_regimes.csv").set_index("strategy")
    for key, field, claimed in (
        ("A. FLEXIBLE — oracle (best pool, cash if all negative)", "ann_return", 0.146),
        ("A. FLEXIBLE — oracle (best pool, cash if all negative)", "sharpe", 3.96),
        ("A. FLEXIBLE — forecast (our strategy)", "ann_return", 0.001),
        ("B. FORCED — always USDC_USDT_1bp", "ann_return", 0.064),
        ("B. FORCED — always USDC_USDT_1bp", "sharpe", 1.96),
        ("B. FORCED — always ETH_USDC_5bp", "ann_return", -0.101),
    ):
        out.append((f"Slide 13 {key[:28]} {field}", claimed, float(r.loc[key, field]), 6e-3))

    d = load("decomposition_fullsample.csv").set_index("pool")
    for pool, field, claimed in (
        ("ETH_USDC_5bp", "net_market_making", -0.0910),
        ("ETH_USDC_30bp", "net_market_making", -0.0231),
        ("ETH_USDC_5bp", "fees", 0.8884),
        ("ETH_USDC_30bp", "fees", 0.9672),
        ("ETH_USDC_5bp", "lvr", 0.9677),
        ("ETH_USDC_30bp", "lvr", 0.9790),
        ("ETH_USDC_30bp", "rebalanced_return", 0.0202),
        ("ETH_USDC_30bp", "total_return", -0.0029),
    ):
        out.append((f"Stage 5 {pool} {field}", claimed, float(d.loc[pool, field]), 5e-4))

    h = load("h3_regression.csv")
    p = h[h.label.str.contains("POOLED")].iloc[0]
    out += [("H3 pooled beta", 0.810, float(p.beta), 2e-3),
            ("H3 pooled R2", 0.618, float(p.r2), 2e-3),
            ("H3 ratio of totals", 0.991, float(p.ratio_totals), 2e-3)]

    r = load("robustness_regimes.csv")
    for name, b in (("calm", 0.963), ("middle", 0.965), ("volatile", 0.753)):
        out.append((f"H3 regime {name} beta", b,
                    float(r[r.period == name].beta.iloc[0]), 2e-3))

    q = load("q2_volatility_estimators.csv").set_index("estimator")
    out += [("Q2 rv_5min ratio", 1.007, float(q.loc["rv_5min", "ratio"]), 2e-3),
            ("Q2 bipower beta", 0.840, float(q.loc["bipower", "beta"]), 2e-3)]

    h6 = load("h6_horse_race.csv").set_index("model")
    for m, v in (("σ²/8 + HAR-RV", 1347.90), ("mean baseline", 1510.49),
                 ("LightGBM", 1610.67)):
        out.append((f"H6 {m} RMSE", v, float(h6.loc[m, "rmse"]), 0.05))
    out.append(("H6 theory OOS R2", 0.126, float(h6.loc["σ²/8 + HAR-RV", "oos_r2"]), 2e-3))

    # The two-pool H7 backtest is superseded by the four-pool allocation on
    # slide 13, so its numbers are no longer deck claims and are not audited.

    pos = load("robustness_position.csv")
    col = "net_market_making" if "net_market_making" in pos.columns else "net_raw"
    g = pos[pos.pool == "ETH_USDC_5bp"].groupby("half_width")[col].mean()
    out += [("Robustness 5bp ±2%", -0.6436, float(g.loc[0.02]), 2e-3),
            ("Robustness 5bp ±50%", -0.0176, float(g.loc[0.50]), 2e-3)]
    return out


def main() -> int:
    rows = claims()
    bad = []
    print(f"{'claim':46s} {'deck':>12s} {'table':>12s}")
    print("-" * 74)
    for label, claimed, actual, tol in rows:
        good = abs(claimed - actual) <= tol
        if not good:
            bad.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:41s} {claimed:12.4f} {actual:12.4f}")
    print(f"\n{len(rows) - len(bad)} match, {len(bad)} mismatch")
    if bad:
        print("\nDECK.md is out of date with:")
        for b in bad:
            print(f"  - {b}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
