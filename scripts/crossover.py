"""Where does liquidity provision stop paying? — placing the sigma crossover.

Six pool averages bracket the crossover between 40% and 52% annualised
volatility, but six points cannot locate anything. This works on the **256
pool-months** behind those averages instead, which is the same data at the
granularity it was measured.

The theory says `net = fees - LVR` with `LVR ~ sigma^2` and fee income driven by
volume, not volatility. So the specification is net on sigma^2, and the
crossover is where the fitted line hits zero.

It also confronts the result that broke the clean story: **WBTC/USDC earns
+4.09% at 40% sigma while WBTC/ETH earns +0.71% at 28% sigma.** If sigma alone
ranked pools that could not happen. The second half of this script tests the
obvious alternative — that fee income per unit of volatility differs across
pairs at the same fee tier — because if it does, sigma sets the cost side only
and ranks pools only when income is comparable.

Inference is clustered by month: pool-months in the same calendar month share a
market, and treating them as independent would overstate precision. Six pools
is too few to cluster on, and that limit is reported rather than hidden.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT

DAILY = REPO_ROOT / "data" / "processed" / "cross_section_daily.parquet"
COHORTS = REPO_ROOT / "outputs" / "tables" / "cohorts_fullsample_all.csv"
OUT = REPO_ROOT / "outputs" / "tables"
#: A $100k position is 113% of ETH/USDC 100bp's active liquidity, so its returns
#: are not price-taking measurements (DECISIONS 5.7). It is shown, never fitted.
EXCLUDE = "ETH_USDC_100bp"
N_BOOT = 5000
RNG = np.random.default_rng(20260908)


def load() -> pd.DataFrame:
    d = pd.read_parquet(DAILY)
    d["year"], d["month"] = d["day"].dt.year, d["day"].dt.month
    # Volatility is a rate, so the monthly summary is a median of daily rates;
    # dollar quantities are summed because they are flows.
    agg = (d.groupby(["pool", "year", "month"])
             .agg(sigma=("sigma_annual", "median"),
                  lvr_usd=("lvr_empirical_usd", "sum"),
                  value_usd=("value_usd", "median"),
                  days=("day", "nunique"))
             .reset_index())
    c = pd.read_csv(COHORTS)[["pool", "fee_tier_bps", "year", "month", "days",
                              "fees", "lvr", "net_market_making",
                              "median_liquidity_share"]]
    c = c.rename(columns={"days": "days_cohort"})
    m = c.merge(agg.drop(columns="days"), on=["pool", "year", "month"], how="inner")
    m["period"] = pd.PeriodIndex(
        pd.to_datetime(dict(year=m.year, month=m.month, day=1)), freq="M")
    # Cohort returns are per-annum rates over a ~1 month holding period; keep
    # them as reported so every number ties back to the decomposition table.
    m["sigma2"] = m["sigma"] ** 2
    return m.dropna(subset=["sigma", "net_market_making"])


def ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_bootstrap_crossover(df: pd.DataFrame, n: int = N_BOOT):
    """Bootstrap the zero-crossing, resampling whole months.

    Resampling months rather than rows keeps the cross-pool correlation within
    a month intact; that correlation is the reason naive standard errors here
    would be far too small.
    """
    months = df["period"].unique()
    by = {p: g for p, g in df.groupby("period")}
    out = []
    for _ in range(n):
        pick = RNG.choice(months, size=len(months), replace=True)
        s = pd.concat([by[p] for p in pick], ignore_index=True)
        X = np.column_stack([np.ones(len(s)), s["sigma2"].to_numpy()])
        b = ols(s["net_market_making"].to_numpy(), X)
        if b[1] < 0 and b[0] > 0:          # a downward line that starts positive
            out.append(float(np.sqrt(-b[0] / b[1])))
    return np.array(out)


def main() -> int:
    m = load()
    fit = m[m.pool != EXCLUDE].copy()
    print("=" * 84)
    print("CROSSOVER — where net market-making crosses zero")
    print("=" * 84)
    print(f"\n{len(m)} pool-months, {m.pool.nunique()} pools; "
          f"fitted on {len(fit)} ({fit.pool.nunique()} pools, {EXCLUDE} excluded)")
    print(f"months: {m.period.min()} to {m.period.max()}\n")

    # ---- 1. the pool-level picture that motivated this -------------------
    lvl = (m.groupby("pool")
             .agg(sigma=("sigma", "median"), fees=("fees", "mean"),
                  lvr=("lvr", "mean"), net=("net_market_making", "mean"),
                  fee_bps=("fee_tier_bps", "first"))
             .sort_values("sigma"))
    print("--- pool level (mean of monthly rates) ---")
    print(lvl.to_string(float_format=lambda v: f"{v:8.4f}"))
    r_all = lvl["sigma"].corr(lvl["net"])
    r_fit = lvl.drop(index=EXCLUDE)["sigma"].corr(lvl.drop(index=EXCLUDE)["net"])
    print(f"\n  corr(sigma, net), all 6 pools : {r_all:+.3f}")
    print(f"  corr(sigma, net), fitted 5    : {r_fit:+.3f}")
    print(f"  spearman, fitted 5            : "
          f"{lvl.drop(index=EXCLUDE)['sigma'].corr(lvl.drop(index=EXCLUDE)['net'], method='spearman'):+.3f}")

    # ---- 2. the crossover on pool-months --------------------------------
    y = fit["net_market_making"].to_numpy()
    X = np.column_stack([np.ones(len(fit)), fit["sigma2"].to_numpy()])
    b = ols(y, X)
    resid = y - X @ b
    r2 = 1 - (resid**2).sum() / ((y - y.mean())**2).sum()
    print(f"\n--- net = a + b*sigma^2, on {len(fit)} pool-months ---")
    print(f"  a = {b[0]:+.4f}   b = {b[1]:+.4f}   R2 = {r2:.3f}")
    if b[1] < 0 and b[0] > 0:
        star = float(np.sqrt(-b[0] / b[1]))
        boot = cluster_bootstrap_crossover(fit)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"\n  crossover sigma* = {star:.1%} annualised")
        print(f"  95% CI (month-clustered bootstrap, {len(boot)}/{N_BOOT} valid)"
              f" = [{lo:.1%}, {hi:.1%}]")
    else:
        star, lo, hi = np.nan, np.nan, np.nan
        print("\n  no downward crossing — the linear form does not locate one")

    # ---- 3. non-parametric check ----------------------------------------
    print("\n--- non-parametric: mean net by sigma decile ---")
    fit["bin"] = pd.qcut(fit["sigma"], 10, duplicates="drop")
    tab = (fit.groupby("bin", observed=True)
              .agg(n=("net_market_making", "size"),
                   sigma=("sigma", "median"),
                   fees=("fees", "mean"), lvr=("lvr", "mean"),
                   net=("net_market_making", "mean"),
                   share_pos=("net_market_making", lambda s: (s > 0).mean())))
    print(tab.to_string(float_format=lambda v: f"{v:8.4f}"))
    pos = tab[tab["net"] > 0]
    neg = tab[tab["net"] < 0]
    if len(pos) and len(neg):
        print(f"\n  last positive decile at sigma {pos['sigma'].max():.1%}; "
              f"first negative at {neg['sigma'].min():.1%}")

    # ---- 4. is the cross-pool relationship reproduced within pools? -----
    print("\n" + "=" * 84)
    print("IS IT VOLATILITY, OR IS IT THE POOL?")
    print("=" * 84)
    print("\nAcross pools, higher sigma goes with lower net. If that is a"
          "\nmechanism rather than composition, it must also hold *inside* a"
          "\npool: volatile months should pay less than calm ones.\n")

    pool_ids = sorted(fit.pool.unique())

    def within_slope(s: pd.DataFrame, ids: list[str]) -> float:
        D = (pd.get_dummies(s.pool).reindex(columns=ids, fill_value=0)
               .astype(float).to_numpy())
        return ols(s["net_market_making"].to_numpy(),
                   np.column_stack([D, s["sigma2"].to_numpy()]))[-1]

    by = {p: g for p, g in fit.groupby("period")}
    keys = list(by)
    boot = np.array([
        within_slope(pd.concat([by[keys[i]] for i in
                                RNG.choice(len(keys), len(keys), replace=True)],
                               ignore_index=True), pool_ids)
        for _ in range(4000)])
    w = within_slope(fit, pool_ids)
    wlo, whi = np.percentile(boot, [2.5, 97.5])
    print(f"  pooled (between pools) slope on sigma^2 : {b[1]:+.4f}")
    print(f"  within-pool slope on sigma^2            : {w:+.4f}")
    print(f"    95% CI (month-clustered)              : [{wlo:+.4f}, {whi:+.4f}]")
    print(f"    P(slope > 0)                          : {np.mean(boot > 0):.3f}")
    print("\n  The sign flips and the within-pool slope cannot be distinguished"
          "\n  from zero. The cross-pool result is a statement about *which pools*"
          "\n  are volatile, not about what volatility does to a given pool.")

    print("\n--- per-pool slope of net on sigma^2 ---")
    for p_, g in fit.groupby("pool"):
        Xg = np.column_stack([np.ones(len(g)), g["sigma2"].to_numpy()])
        bb = ols(g["net_market_making"].to_numpy(), Xg)
        print(f"  {p_:16s} n={len(g):3d}  b={bb[1]:+9.4f}")

    # ---- 5. the mechanism, corrected -------------------------------------
    print("\n" + "=" * 84)
    print("THE MECHANISM: BOTH SIDES SCALE WITH VARIANCE")
    print("=" * 84)
    print("\nThe claim this project carried was that LVR scales with sigma^2"
          "\nwhile fee income does not. In this sample that is false: volume"
          "\nrises with volatility, so fee income scales with sigma^2 almost as"
          "\nsteeply as LVR does.\n")
    for col in ("fees", "lvr"):
        Xc = np.column_stack([np.ones(len(fit)), fit["sigma2"].to_numpy()])
        bb = ols(fit[col].to_numpy(), Xc)
        rr = fit[col].to_numpy() - Xc @ bb
        rsq = 1 - (rr**2).sum() / ((fit[col] - fit[col].mean())**2).sum()
        print(f"  {col:5s} = {bb[0]:+.4f} {bb[1]:+.4f}*sigma^2   R2={rsq:.3f}")
    print("\n  Net is the small difference between two large, near-parallel"
          "\n  terms, which is why R2 on net is only "
          f"{r2:.3f} and the crossover CI is wide.")

    print("\n--- LVR per unit variance, ordered by volatility ---")
    cost = {}
    for p_, g in fit.groupby("pool"):
        Xg = np.column_stack([np.ones(len(g)), g["sigma2"].to_numpy()])
        cost[p_] = (float(g["sigma"].median()), ols(g["lvr"].to_numpy(), Xg)[1])
    for p_, (sig, c) in sorted(cost.items(), key=lambda kv: kv[1][0]):
        print(f"  {p_:16s} sigma {sig:6.3f}   LVR/sigma^2 {c:9.3f}")
    print("\n  NOT a constant with one exception. Ordered by volatility this is a"
          "\n  continuum: 41.8 at 2.3% sigma, 5.2 at 19.5%, then 3.1-3.5 from 28%"
          "\n  upward, where it flattens. The adverse-selection floor H3 found on"
          "\n  the peg is present at every volatility and merely becomes small"
          "\n  relative to the diffusive term once sigma is high enough.")
    print("\n  An earlier version of this script asserted ~3.3 on every non-peg"
          "\n  pool. Adding a pool at 19.5% sigma - the region the claim had never"
          "\n  been tested in - returned 5.2 and falsified it.")

    # ---- 6. a better ranking variable, and its limits ---------------------
    print("\n" + "=" * 84)
    print("RANKING POOLS: FEE INCOME PER UNIT VARIANCE")
    print("=" * 84)
    fit["ratio"] = fit["fees"] / fit["sigma2"]
    lv = fit.groupby("pool").agg(sigma=("sigma", "median"),
                                 ratio=("ratio", "median"),
                                 net=("net_market_making", "mean"))
    print()
    print(lv.sort_values("ratio").to_string(float_format=lambda v: f"{v:10.3f}"))
    print(f"\n  corr(sigma, net)        = {lv.sigma.corr(lv.net):+.3f}  "
          f"(spearman {lv.sigma.corr(lv.net, method='spearman'):+.3f})")
    print(f"  corr(fees/sigma^2, net) = {lv.ratio.corr(lv.net):+.3f}  "
          f"(spearman {lv.ratio.corr(lv.net, method='spearman'):+.3f})")
    print("\n  This ranked all five pools perfectly before the gold pool was added"
          "\n  and now ranks six at Spearman +0.83. The pool it misplaces is the"
          "\n  one that broke the constant: PAXG clears a 3.3 threshold on fee"
          "\n  income (3.41) yet loses money, because its OWN cost side is 5.2."
          "\n  A single threshold only works where LVR/sigma^2 is flat, which is"
          "\n  above roughly 28% annualised. Below that the threshold is"
          "\n  pool-specific and the rule reduces to a tautology."
          "\n  Note also that it is partly mechanical: net = fees - LVR.")

    # The honest test of a signal is whether it works with a lag.
    f = fit.sort_values(["pool", "period"]).copy()
    f["ratio_lag"] = f.groupby("pool")["ratio"].shift(1)
    f["sigma_lag"] = f.groupby("pool")["sigma"].shift(1)
    g2 = f.dropna(subset=["ratio_lag", "sigma_lag"])
    hit_r = g2.groupby("period").apply(
        lambda s: s["net_market_making"].to_numpy()[
            s["ratio_lag"].to_numpy().argmax()] > 0, include_groups=False).mean()
    hit_s = g2.groupby("period").apply(
        lambda s: s["net_market_making"].to_numpy()[
            s["sigma_lag"].to_numpy().argmin()] > 0, include_groups=False).mean()
    print(f"\n--- as a tradeable signal, lagged one month ({len(g2)} pool-months) ---")
    print(f"  pick highest lagged fees/sigma^2 -> net > 0 in {hit_r:.1%} of months")
    print(f"  pick lowest  lagged sigma        -> net > 0 in {hit_s:.1%} of months")
    print("\n  The better cross-sectional descriptor is NOT the better forecast."
          "\n  Consistent with the oracle decomposition: the binding constraint"
          "\n  is predicting fee income, not describing it after the fact.")

    rows = [{"metric": f"lvr_per_var_{k}", "value": float(v[1]), "lo": np.nan,
             "hi": np.nan} for k, v in cost.items()]
    rows += [{"metric": "spearman_ratio_net", "value":
              float(lv.ratio.corr(lv.net, method="spearman")), "lo": np.nan, "hi": np.nan},
             {"metric": "crossover_sigma", "value": star, "lo": lo, "hi": hi},
            {"metric": "corr_sigma_net_all", "value": r_all, "lo": np.nan, "hi": np.nan},
            {"metric": "corr_sigma_net_fitted", "value": r_fit, "lo": np.nan, "hi": np.nan},
            {"metric": "slope_between_pools", "value": b[1], "lo": np.nan, "hi": np.nan},
            {"metric": "slope_within_pool", "value": w, "lo": wlo, "hi": whi},
            {"metric": "p_within_slope_positive", "value": float(np.mean(boot > 0)),
             "lo": np.nan, "hi": np.nan},
            {"metric": "intercept", "value": b[0], "lo": np.nan, "hi": np.nan},
            {"metric": "r2_net_on_sigma2", "value": r2, "lo": np.nan, "hi": np.nan},
            {"metric": "hit_rate_lagged_ratio", "value": float(hit_r), "lo": np.nan, "hi": np.nan},
            {"metric": "hit_rate_lagged_sigma", "value": float(hit_s), "lo": np.nan, "hi": np.nan}]
    pd.DataFrame(rows).to_csv(OUT / "crossover.csv", index=False)
    tab.reset_index().astype({"bin": str}).to_csv(OUT / "crossover_deciles.csv",
                                                  index=False)
    lv.reset_index().to_csv(OUT / "crossover_ranking.csv", index=False)
    print("\nwrote crossover.csv, crossover_deciles.csv, crossover_ranking.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
