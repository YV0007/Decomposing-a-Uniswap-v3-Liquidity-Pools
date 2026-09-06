"""H3 — does the sigma^2/8 closed form track observed adverse selection?

    empirical_LVR(t) = alpha + beta * analytical_LVR(t) + eps

Prediction: beta = 1, alpha = 0. Newey-West standard errors, because both series
are highly persistent and plain OLS errors would overstate the precision of beta
— on this question that is the difference between "the theory holds" and "we
cannot tell".

**The gap is itself the finding.** Where the theory breaks — high volatility,
thin liquidity, wide ranges — is what quantifies how much of a frictionless
derivation survives real gas, discrete blocks and fee tiers. This gets its own
slide whatever the outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.build.derived import available_months
from src.build.h3 import daily_lvr
from src.utils.config import REPO_ROOT, pools
from src.utils.plotting import lvr_theory_vs_empirical, save_figure
from src.utils.speclog import log_specification
from src.utils.stats import newey_west_ols

CACHE = REPO_ROOT / "data" / "processed" / "h3_daily.parquet"
#: The 100bp pool has no viable position size (DECISIONS 5.7), so its LVR is not
#: a measurement of anything. Kept in the data, excluded from the headline.
HEADLINE_POOLS = ("ETH_USDC_5bp", "ETH_USDC_30bp")


def build(force: bool = False) -> pd.DataFrame:
    if CACHE.exists() and not force:
        return pd.read_parquet(CACHE)
    frames = []
    for spec in pools("core"):
        for y, m in available_months(spec):
            try:
                frames.append(daily_lvr(spec, y, m))
                print(f"  {spec.id} {y}-{m:02d}", flush=True)
            except Exception as exc:
                print(f"  {spec.id} {y}-{m:02d}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
    out = pd.concat(frames, ignore_index=True).sort_values(["pool", "day"])
    out.to_parquet(CACHE, index=False)
    return out


def report(df: pd.DataFrame, label: str) -> dict:
    d = df.dropna(subset=["lvr_empirical_usd", "lvr_analytical_usd"])
    d = d[(d["lvr_analytical_usd"] > 0) & d["lvr_empirical_usd"].notna()]
    if len(d) < 30:
        print(f"  {label}: only {len(d)} usable days, skipping")
        return {}
    fit = newey_west_ols(d["lvr_empirical_usd"], d["lvr_analytical_usd"])
    lo, hi = fit.beta_ci()
    p = fit.beta_equals(1.0)
    print(f"\n--- {label}  (n = {fit.n_obs:,} days, NW lags {fit.nw_lags}) ---")
    print(f"  beta   {fit.beta:+.4f}   se {fit.beta_se:.4f}   95% CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"  alpha  {fit.alpha:+.4f}   se {fit.alpha_se:.4f}   t {fit.alpha_t:+.2f}")
    print(f"  R^2    {fit.r_squared:.4f}")
    print(f"  H0: beta = 1  ->  p = {p:.4f}  "
          f"{'CANNOT REJECT — theory holds' if p > 0.05 else 'REJECTED'}")
    print(f"  ratio of totals: {d.lvr_empirical_usd.sum() / d.lvr_analytical_usd.sum():.4f}")
    return {"label": label, "n": fit.n_obs, "beta": fit.beta, "beta_se": fit.beta_se,
            "ci_low": lo, "ci_high": hi, "alpha": fit.alpha, "alpha_se": fit.alpha_se,
            "r2": fit.r_squared, "p_beta_eq_1": p,
            "ratio_totals": d.lvr_empirical_usd.sum() / d.lvr_analytical_usd.sum(), "_fit": fit}


def main() -> int:
    print("=== building daily LVR series ===", flush=True)
    df = build()
    print(f"\n{len(df):,} pool-days across {df.pool.nunique()} pools\n")

    results = []
    head = df[df.pool.isin(HEADLINE_POOLS)]
    r_all = report(head, "POOLED (5bp + 30bp)")
    results.append(r_all)
    for pid, g in df.groupby("pool", sort=False):
        note = "" if pid in HEADLINE_POOLS else "  [excluded from headline: no viable size]"
        r = report(g, pid + note)
        if r:
            results.append(r)

    print("\n--- where does the theory break? residuals by regime ---")
    d = head[(head.lvr_analytical_usd > 0)].copy()
    fit = r_all["_fit"]
    d = d.iloc[: len(fit.residuals)] if len(d) != len(fit.residuals) else d
    d["resid"] = fit.residuals[: len(d)]
    d["abs_resid"] = d["resid"].abs()
    for col, name in (("sigma_annual", "volatility"), ("share_in_range", "share in range"),
                      ("n_blocks", "trade intensity")):
        # A column with too few distinct values cannot be split into quartiles —
        # `share_in_range` is 1.0 almost everywhere once the position re-centres.
        if d[col].nunique() < 8:
            print(f"\n  by {name}: skipped, only {d[col].nunique()} distinct values")
            continue
        try:
            q = pd.qcut(d[col], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        except ValueError:
            q = pd.qcut(d[col].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
        g = d.groupby(q, observed=True).agg(
            mean_resid=("resid", "mean"), mean_abs=("abs_resid", "mean"),
            emp=("lvr_empirical_usd", "sum"), ana=("lvr_analytical_usd", "sum"))
        g["emp_over_ana"] = g.emp / g.ana
        print(f"\n  by {name}:")
        print(g[["mean_resid", "mean_abs", "emp_over_ana"]].to_string(
            float_format=lambda v: f"{v:9.3f}"))

    out = REPO_ROOT / "outputs" / "tables"
    pd.DataFrame([{k: v for k, v in r.items() if k != "_fit"} for r in results if r]).to_csv(
        out / "h3_regression.csv", index=False)

    fig = lvr_theory_vs_empirical(head["lvr_empirical_usd"], head["lvr_analytical_usd"], fit)
    p = save_figure(fig, "h3_theory_vs_empirical", "h3_regression.py")
    log_specification(stage="3", component="h3_regression",
                      params={"frequency": "daily", "pools": list(HEADLINE_POOLS),
                              "se": "newey_west"},
                      metric_name="beta", metric_value=r_all["beta"],
                      notes="H3 pooled regression, full sample")
    print(f"\nwrote outputs/tables/h3_regression.csv and {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
