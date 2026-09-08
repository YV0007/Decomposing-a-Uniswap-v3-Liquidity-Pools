# What is left, in execution order — 8 September 2026

Each step lists why it must come where it does. The ordering is a dependency
chain: steps 1–2 change numbers that steps 3–7 report.

---

## 1. Re-run everything that stood on the broken panel  ⚠️ blocking

A stale fee cache gave WBTC/USDC zero fees for all 188 weeks. `build_panel.py`
is fixed and guarded, and the allocation is re-run, but **`stage6_h5_h6.py` and
`stage7_backtest.py` read the same panel** and their tables on disk predate both
the fix and the sixth pool.

- re-run `build_panel.py` (done), `allocation_regimes.py` (done)
- re-run `stage6_h5_h6.py` — H5 forecast, H6 horse race
- re-run `stage7_backtest.py` — the original H7 backtest
- add a regression test that a pool in the universe with zero fee rows raises

Nothing downstream is trustworthy until this is finished.

## 2. Place the crossover, and confront the non-monotonicity

The sixth pool was added to narrow a 28–52% bracket. It did, but it also broke
the clean story: **+4.09% at 40% σ is better than +0.71% at 28% σ.** Pearson
`corr(σ, net)` falls from −0.923 on four pools to **−0.592 on six** (Spearman
−0.886).

- fit net return on σ across six pools; report where it crosses zero with a CI
- test whether fee income per unit volume, not σ, explains the reordering
  (WBTC/USDC earns +61% fees against WBTC/ETH's +33% at the same 30bp tier)
- state the honest conclusion: σ sets the cost side and ranks pools only when
  fee income is comparable

## 3. Strengthen or retire the static rule

"Always hold the lowest-σ pool" earns +6.4% at Sharpe 1.96 but scores **0.83
against a 0.95 deflated-Sharpe bar**, on one peg pool over 165 weeks.

- test the rule out-of-sample by period, and on the second-lowest-σ pool
- report it as a hypothesis with a stated failure mode, not a recommendation,
  unless it clears the bar

## 4. Explain 2023

β is 0.372 in 2023 against 0.918–0.944 later, and this is still unexplained.
Candidates: thinner arbitrage, wider no-arbitrage bands, different MEV
infrastructure. Resolve it or state it as a known limitation.

## 5. Regenerate every figure

`make_figures.py` against the six-pool tables, so no chart is a pool behind.

## 6. Update the written record

- `DECISIONS.md` — the fee-cache defect, the non-monotonicity, the reversal of
  `corr(σ, net) = −0.923`
- `PHASE_REPORT.md` / `DECK.md` — the sixth pool, the revised strategy table
- re-run `audit_deck.py` (44 checks) so no slide can drift from its table

## 7. Full reproduction and commit

`reproduce.py --full` end to end, then commit. The standard is that every
number in the deck regenerates from the repo and the config.
