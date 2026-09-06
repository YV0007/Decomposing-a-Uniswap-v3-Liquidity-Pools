# LVR/MEV — Where We Are

**Status as of 6 September 2026.** 12 commits · 217 tests passing · 8.58M swaps · 44 months of perp + DVOL · 4.3 GB on disk

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
  🟡 5. Decomposition      fees − LVR − MEV − gas.  Built; run on 1 month only
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

**Remaining.** The formal H3 regression — empirical on analytical, with
Newey-West errors — hasn't been run yet. The machinery is built and tested; it
needs the full-sample series to regress. Also the volatility-estimator horse race
(open question 2): which estimator best matches observed LVR.

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

## Stage 5 — Decomposition 🟡

*The headline table: advertised yield versus what an LP actually keeps.*

**Built and run for January 2023.** The pipeline runs end to end across all three
pools. It also produces the *bridge* — why the advertised number overstates
reality — which turned out to qualify our own thesis:

| | 5bp | 30bp | 100bp |
|---|---|---|---|
| Advertised APR | 40.41% | 15.48% | 12.28% |
| …of which range management | −29.46% | −11.27% | −8.85% |
| …of which LVR + gas | −5.80% | −6.26% | −5.88% |
| **Realised net** | **+0.67%** | **−0.55%** | **+0.92%** |

Range management is 70–78% of the gap; adverse selection is 15–52%. Saying
"advertised 40% is really 0.7% because of LVR" would overstate the result about
fivefold. LVR is the *irreducible* part — an LP can manage range cost away and
cannot manage LVR away.

**Remaining.**
- Run across all 44 months, not one
- The delta-hedged variant (see the warning above)
- Confidence intervals on every figure
- Compare fee tiers at fixed *realised* width — the tiers have different tick
  spacings, so they can't hold the same range, which is a confound in H4
- Monthly cohorts instead of a single entry date

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

## Honest summary

**Solid.** The data layer, the measurement of fees and LVR, and the range-width
mathematics. Each passed a gate that could have failed, and three real defects
were caught by those gates rather than by luck.

**Thin.** Everything empirical rests on one month. January 2023 was a 40%
uptrend, which is the regime least favourable to a fee band. Whether that month's
conclusions generalise is genuinely unknown, and the full-sample run is what
settles it.

**Open questions: 5 of 7 closed.** Remaining: which volatility estimator best
matches observed LVR (Q2), and optimal fee tier as a function of volatility (Q5).

**Next three steps, in order:**
1. Run Stage 5 across all 44 months, hedged and raw, with confidence intervals
2. Run the H3 regression on the full series — the paper's core theoretical claim
3. Build the forecast model and the theory-versus-ML horse race

Nothing is blocked. The derived layer finishes in the background, and every
input those three steps need is now on disk.
