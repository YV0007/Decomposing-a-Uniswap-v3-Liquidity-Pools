# LVR/MEV — Where We Are

**Status as of 6 September 2026.** 15 commits · 220 tests · 5,554 lines of code · 8.58M swaps · 4.7 GB

**Headline result is in.** A re-centred ±10% LP position on ETH/USDC lost money
over 43 months, significantly so on the 5bp pool. Details in Stage 5 below.

Read top to bottom. Each stage feeds the next, and a stage cannot be trusted
until the one before it has passed its gate.

---

## The chain at a glance

```
  ✅ 0. Decisions          settled in writing before any code
       ↓
  ✅ 1. Data layer         swaps + CEX prices, aligned, gate passed
       ↓
  ✅ 2. Position & fees    what an LP holds and earns, gate passed
       ↓
  ✅ 3. LVR                what arbitrageurs take, gate passed
       ↓
  ✅ 4. MEV               sandwich detection + attribution decided
       ↓
  ✅ 5. Decomposition      fees − LVR − MEV − gas.  Full sample, 43 cohorts × 3 pools
       ↓
  🟡 H3. Theory test       σ²/8 vs observed.  Structure confirmed; regression not run
       ↓
  ⬜ 6. Forecasting        can net return be predicted?  Machinery built, model not
       ↓
  ⬜ 7. Strategy           allocate across pools, backtest with full costs
       ↓
  ⬜ 9. Deck & write-up    15 slides + appendix

  ✅ 8. Range width        (parallel track) the original mathematics — DONE
  ✅ D. Delta hedging      (cuts across 5–7) BUILT — hourly, not daily
```

Legend: ✅ done and gated · 🟡 partly done · ⬜ not started

---

## Infrastructure — all built ✅

Everything needed before the analysis stages can run now exists.

**Data collected.** Perpetual 1-minute prices and realised funding for all 44
months (spot cannot stand in for the perp — the basis is exactly what funding
pays to close). Deribit DVOL hourly for all 44 months, the implied-volatility
feature. Both free, no keys.

**Delta hedging built**, which was the flagged gap, and measuring it settled a
standing question. A perfect hedge leaves LP value change plus hedge P&L equal
to fees minus LVR — near zero in January 2023 — so the residual *is* the hedging
error:

| Rebalance | residual | mean unhedged exposure |
|---|---|---|
| Hourly | −$392 | $88 |
| Daily | −$715 | $952 |
| Weekly | −$5,140 | $7,445 |

The daily error exceeds the entire market-making return being measured, so
hedging daily would have made the "cleaner" variant noisier than the raw one.
**Baseline moved from daily to hourly** for about $22 more trading cost.

**Derived data layer.** One cached table per pool-month — price, tick,
liquidity, aligned CEX reference, volatility — so the remaining stages load
instead of recompute. Currently building in the background (~2 hours).

**Also built:** HAR-RV / EWMA / GARCH volatility forecasts, monthly entry
cohorts, the feature matrix and its no-lookahead gate, and the figure module.

One test caught a real leak in my own code: HAR was training on labels whose
window extended past the forecast origin — the same purging problem, inside the
forecast. Fixed; it still finds signal (corr 0.66) on a persistent process.

---

## Stage 0 — Decisions ✅

*Settle the choices that propagate into every table, in writing, before coding.*

**Done.** Delta-hedged chosen as primary; position spec fixed ($100k, ±10%,
re-centre on range exit, monthly cohorts); universe fixed (ETH/USDC at 5/30/100bp
first). Every entry records what was decided, why, and what would reverse it.

Two decisions changed later and are logged as reversals rather than quietly
edited: the data source (Dune → raw chain logs) and MEV attribution
(flow-toxicity → neutral).

**Remaining.** Nothing. Living document; new decisions get appended.

---

## Stage 1 — Data layer ✅

*Get the swap history and a reference price, and prove the prices are right.*

**Done.** Reads Uniswap v3 events directly from Ethereum archive nodes rather
than Dune — exact integers, no API key, three providers to cross-check. Binance
1-second klines as the reference price, aligned to blocks by a strictly causal
rule (no peeking forward, enforced by test).

**Gate passed.** Every one of 9,959 reconstructed prices fell inside the
one-basis-point band implied by the tick the pool itself reported, and `slot0()`
read at historical blocks matched the logs exactly.

**Full sample fetched:** 44 months (Jan 2023 – Aug 2026), 8.58M swaps across all
three pools, 43 months of second-resolution CEX prices.

**Remaining.** Binance has not yet published August 2026 klines, so the CEX
series ends July 2026 and the final month of swaps has no reference price. Drop
that month or accept a 43-month sample.

---

## Stage 2 — Position and fees ✅

*Reconstruct what an LP position holds, is worth, and earns.*

**Done.** Position sizing, valuation, delta, range state, and fee accrual.
Validated against a method the plan didn't specify and which is better as a
reference: reading `feeGrowthInside` from the pool contract, which reproduces
Uniswap's own arithmetic exactly.

**Gate passed** at +0.18% / −0.52% against a 2% tolerance.

**Remaining.** Nothing. Monthly entry cohorts are now built.

---

## Stage 3 — LVR ✅

*Measure what arbitrageurs extract, and test it against the σ²/8 theory.*

**Done.** Three measures rather than two, because they answer different
questions — one assumes perfect arbitrage every block (what theory predicts),
one measures what the pool price actually did (where the fee-tier effect lives),
one is the closed form. Splitting them mattered: reporting a single "empirical
LVR" would have made H4 untestable without anyone noticing.

**Gate passed** on all four checks.

**Remaining — and this is the next step.** The formal H3 regression, empirical
LVR on analytical with Newey-West errors, has not been run. The prediction is
β = 1, α = 0. All three series exist for all 43 months and the regression
machinery is built and tested; it needs assembling, not building.

Stage 8 already confirms the *structure* — fees and LVR scale identically with
range width, and the closed form matches measured LVR to 3.4% — so this is the
formal test of a claim already supported informally.

Also open: which volatility estimator best matches observed LVR (Q2).

---

## Stage 4 — MEV ✅

*Find sandwich attacks and decide what they cost the LP.*

**Done.** The classifier as specified turned out to be mostly false positives —
45% of detections lost money, and the largest sold $1.25M and bought back $10k.
Requiring the back leg to actually unwind the front leg cut 2,620 candidates to
241 and $1.57M of attacker profit to $394k. The surviving set unwinds almost
exactly, which is what real searchers do.

Attribution decided: **neutral**. Walking a sandwich through from the LP's side,
the LP round-trips, ends near the inventory the victim alone would have left it,
and earns three fees instead of one. The victim pays, not the LP.

**Remaining.** Sensitivity table across classification rules. Bundle-level
detection is impossible — the Flashbots public relay only serves recent blocks —
so the count is a one-sided undercount, and that's a stated limitation.

---

## Stage 5 — Decomposition ✅

*The headline table: what an LP actually keeps.*

**Done across the full sample.** 43 monthly cohorts per pool, 2023-01 to
2026-07, $100k at ±10%, re-centred on exit, hourly hedge, bootstrap intervals.

| Pool | fees | LVR | gas | **net (raw)** | 95% CI | **net (hedged)** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|---|---|
| ETH/USDC 5bp | +88.84% | −96.77% | −1.17% | **−9.10%** | [−15.6%, −3.3%] | **−14.06%** | [−22.0%, −7.0%] | 26% |
| ETH/USDC 30bp | +96.72% | −97.90% | −1.14% | **−2.31%** | [−5.2%, +1.3%] | **−6.34%** | [−9.4%, −3.3%] | 21% |
| ETH/USDC 100bp | — | — | — | *withheld* | — | *withheld* | — | — |

**The position lost money.** Significant on 5bp both ways. On 30bp the raw
interval spans zero but the hedged one does not — stripping the directional beta
is what makes the loss visible, which is why Stage 0 chose the hedged variant.

The fee/LVR ratio is 0.918 and 0.988: LPs earn very nearly, but not quite,
enough to cover adverse selection.

**The 100bp row is withheld** because no position size works there. At $1,000 it
is a price-taker and gas destroys it (−94.8%); at $100k it holds 113% of the
pool's active liquidity and is not a price-taker at all. The viable window is
empty — which is itself the finding, and explains 655 swaps a month.

Also produced the *bridge* from advertised APR to realised net (January 2023),
which qualifies our own thesis: range management is 70–78% of the gap and
adverse selection 15–52%. LVR is the *irreducible* part — an LP can manage range
cost away and cannot manage LVR away.

**Remaining.** Robustness sweeps across the full sample: range width,
re-centring rule, hedge frequency, alternative MEV rules, subperiods.

---

## Stage 6 — Forecasting ⬜

*Can next week's net return be predicted? And does theory beat machine learning?*

**Machinery and features built and tested.** The feature matrix, its
no-lookahead gate, and the volatility forecasts that form the theory arm of the
horse race. Purged, embargoed cross-validation (with a test
proving the purge actually closes a leak, rather than silently doing nothing);
Newey-West standard errors; the deflated Sharpe ratio; a specification log that
records every configuration as it is run, so the multiple-testing count is
honest rather than reconstructed.

**Remaining.** The LightGBM model and the head-to-head between the σ²/8 closed
form and the black box. This is the horse race where theory winning would be the
stronger result.

**Depends on** Stage 5 across the full sample — the target is net LP return, so
there is nothing to predict until that exists.

---

## Stage 7 — Strategy ⬜

*Allocate capital across pools weekly and see whether it beats the benchmarks.*

**Not started.** Needs the allocation rule, the backtest with full costs from the
first run, and four benchmarks including the deliberately unbeatable one
(best single pool in hindsight).

A negative result is a legitimate finding here and is permitted: "advertised LP
yields are systematically overstated and this strategy does not recover them" is
a defensible paper.

**Depends on** Stage 6.

---

## Stage 8 — Optimal range width ✅ ⭐

*Original mathematics. Was an appendix; the Stage 5 bridge promoted it.*

**Done, and it produced the strongest result so far.** Derived a closed form for
the best range width and validated it against real data — it matches a grid
search to 0.02%.

The finding that matters is structural: **fees and LVR both scale the same way
with range width.** Narrowing a range amplifies income and adverse selection
*identically*, so concentration sets the size of the outcome but never its sign.
An LP cannot fix an unprofitable pool by picking a cleverer range.

Confirmed in the data: across a 34× span of range widths, the ratio of fees to
LVR moved by 1.85%.

Also answered a standing open question: two things limit how narrow a range can
be, and the tick grid binds twenty times before position size does — capacity
isn't a constraint below about $2M on this pool.

**Remaining.** Optimal *fee tier* as a function of volatility (`theory/fee_tier.py`
is still a stub) — the natural companion result.

---

## Stage 9 — Deck and write-up ⬜

**Not started.** 15 slides plus appendix. The figure module is built — waterfall,
H3 scatter, range-width sweep, hedge error and gap distribution — and every
figure stamps its own git revision and config hash so it can be traced back to
what made it.

---

## Defects found and fixed

Six, all of the kind that produce plausible numbers rather than errors. Listed
because the gates catching them is the main evidence the pipeline is sound.

| # | What | How it showed |
|---|---|---|
| 1 | int24 ticks read at declared width; ABI sign-extends | tick −2 decoded as a 78-digit number; invisible on ETH/USDC, universal on USDC/USDT |
| 2 | pandas inferred int64 for amount columns from the data | a quiet month would silently overflow above 9.22 WETH |
| 3 | Fees lost at the range boundary | −1.88% vs the contract; localised to one crossing swap |
| 4 | Sandwich classifier mostly false positives | 45% of "sandwiches" lost money; top 1% carried 105% of profit |
| 5 | Fee share ignored the position's own liquidity | flipped the 100bp headline from +34.65% to −43.10% |
| 6 | HAR trained on labels reaching past the forecast origin | caught by my own test; the purging problem inside the forecast |

## Hypotheses

| | Claim | State |
|---|---|---|
| H1 | The decomposition is computable | ✅ all gates passed |
| H2 | Advertised yields overstate returns | ✅ confirmed, and qualified — range management dominates, LVR is the irreducible part |
| H3 | σ²/8 holds | 🟡 structure confirmed; formal regression outstanding |
| H4 | Fee tier is the dominant determinant | ⚠️ weakened — tick spacing is confounded with fee tier, and the 100bp arm is unusable. Really 5bp vs 30bp |
| H5 | Net return is forecastable | ⬜ not started |
| H6 | Theory beats ML on LVR | ⬜ not started |
| H7 | Economic significance | ⬜ not started |

## Honest summary

**Solid.** The data layer, fees, LVR, the full-sample decomposition, and the
range-width mathematics. Every gate could have failed and six real defects were
caught by them.

**Weakened.** H4. Uniswap bundles tick spacing with fee tier, and the 100bp pool
has no viable position size, so the three-way natural experiment is a two-way
one.

**Untouched.** Forecasting, the strategy backtest, and the deck.

**Open questions: 5 of 7 closed.** Remaining: which volatility estimator best
matches observed LVR (Q2), and optimal fee tier as a function of σ (Q5).

**Next three steps, in order:**
1. The H3 regression on the full series — the paper's core theoretical claim, and
   the only remaining piece of the *measurement* half
2. The forecast model and the theory-versus-ML horse race (H5, H6)
3. The strategy backtest with full costs and a deflated Sharpe (H7)

Nothing is blocked. Every input those steps need is on disk.
