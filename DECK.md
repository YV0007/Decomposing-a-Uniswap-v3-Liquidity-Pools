# The True Cost of Providing Liquidity
**LVR, MEV, and the net return to Uniswap v3 market making**

15 slides + appendix. Every number traces to a table in `outputs/tables/` and
every figure to `scripts/make_figures.py`. Figures carry the git revision and a
hash of `config.yaml` in their metadata.

---

## 1 — Title

**The True Cost of Providing Liquidity**
LVR, MEV, and the net return to Uniswap v3 market making

Repo · 8.58M swaps · 43 months · 250+ tests · every gate and every defect logged

> *Speaker note.* The one-line claim: over three and a half years, ETH/USDC
> liquidity providers earned fees covering 92–99% of the adverse selection they
> paid, and the shortfall is statistically significant on the busiest pool.

---

## 2 — Motivation: an AMM has no oracle

A pool prices from a formula, not a feed. It has no idea what ETH costs on
Binance and no mechanism to find out. **Its price updates only when someone
trades against it**, so after any move on a centralised venue it is stale —
quoting the old price.

Nobody is paid to fix this. Independent searchers do it as a side effect of
making money: they buy the underpriced side from the pool and sell on Binance.
That money comes out of the LP.

**This is LVR: a systematic transfer from passive liquidity providers to
informed arbitrageurs, on every meaningful price move, permanently.**

*Figure: the staleness diagram — pool price stepping, CEX price continuous.*

> *Speaker note.* Emphasise that this is structural, not a bug. As long as an
> AMM prices from a formula rather than a feed, it is stale after every move.

---

## 3 — Who pays, and why nobody notices

| Flow | Informed? | Effect on the LP |
|---|---|---|
| Arbitrageurs | Yes, by construction | **Loses money** — they trade precisely when the pool is wrong |
| Retail swappers | No | **Makes money** — they pay fees and leave |
| Aggregator routing | Mixed | Neutral to slightly negative |

LVR is an **opportunity cost, not a line item**. No transaction is labelled
"arbitrageur took $400 from you". It shows up only as your position being worth
less than a continuously rebalanced portfolio would have been.

Every dashboard shows fees earned. None shows this.

> *Speaker note.* Same adverse-selection problem every market maker faces. The
> difference from a Deribit dealer is not the economics — it is that the dealer
> hedges and models it, and most LPs do not know it is happening.

---

## 4 — LVR is not impermanent loss

| | Compares against | Measures |
|---|---|---|
| **Impermanent loss** | Holding the two tokens | The cost of the AMM's rebalancing |
| **LVR** | A continuously rebalanced portfolio with the same delta | The cost of being *stale* |

Routinely conflated. The distinction is what makes LVR the right object: it
isolates adverse selection from directional exposure.

**And it has a consequence used throughout this paper.** From
`AMM_return = rebalanced_return + fees − LVR`, the quantity `fees − LVR` is
*already delta-hedged by construction*. That identity is the spine of the
decomposition.

---

## 5 — Data and construction

| Source | What | Scale |
|---|---|---|
| Ethereum archive RPC (`eth_getLogs`) | Uniswap v3 swaps | **8.58M swaps**, 44 months, 3 pools |
| Binance `data.binance.vision` | 1-second klines, perp klines, funding | 43 months |
| Deribit public API | DVOL implied volatility | 44 months |
| Pool contracts (`eth_call`) | TVL, `feeGrowthInside`, tick state | historical blocks |

**Total cost: €0. No API keys.**

Substituted raw chain logs for the planned Dune source: exact hex integers, no
intermediary decoding, native `logIndex` ordering for MEV work, and three
independent providers to cross-check.

**Universe:** ETH/USDC at 5bp, 30bp, 100bp. 2023-01 to 2026-07.

---

## 6 — H1: does the reconstruction hold up? ✅

Every stage passed a gate that could have failed.

| Gate | Criterion | Result |
|---|---|---|
| Stage 1 | price inside the 1bp band implied by the pool's own tick | **0 of 9,959 outside** |
| Stage 1 | `slot0()` at historical blocks matches the logs | **10/10 exact** |
| Stage 2 | fee replay within 2% of the contract's `feeGrowthInside` | **+0.18% / −0.52%** |
| Stage 3 | LVR positive, plausible, same order as theory | **all four checks** |
| Stage 6 | purged CV demonstrably closes a leak | **pass, both directions** |

**Nine defects were caught by these gates**, every one producing plausible
numbers rather than errors. Listed in the appendix — that list is the main
evidence the pipeline is sound.

---

## 7 — H2: the decomposition ⭐

43 monthly cohorts per pool, $100k at ±10%, re-centred on exit.

| Pool | fees | LVR | gas | **market-making** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|
| ETH/USDC 5bp | +88.84% | −96.77% | −1.17% | **−9.10%** | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | +96.72% | −97.90% | −1.14% | **−2.31%** | [−5.2%, +1.3%] | 21% |

**Fees covered 92% and 99% of LVR.** The 5bp shortfall is significant; the 30bp
interval spans zero. One month in four or five was profitable.

**The advertised-to-realised bridge, and the honest caveat:** advertised APR was
40.41% on the 5bp pool against a realised net near zero — but **range management
is 70–78% of that gap and adverse selection only 15–52%**. Saying "advertised
40% is really 0.7% because of LVR" would overstate our own result about
fivefold. LVR is the *irreducible* part: an LP can manage range cost away and
cannot manage LVR away.

*Figures: `waterfall_ETH_USDC_5bp.png`, `waterfall_ETH_USDC_30bp.png`*

---

## 8 — H3: does σ²/8 hold? ⭐

3,842 pool-days. Empirical LVR on analytical, Newey-West errors.

| Sample | β | 95% CI | R² | ratio of totals |
|---|---|---|---|---|
| Pooled | **0.810** | [0.672, 0.948] | **0.618** | **0.991** |

**The closed form explains 62% of daily LVR variation with zero fitted
parameters**, and predicts the aggregate three-and-a-half-year transfer to
within 1%.

**The slope is significantly below one, and that is the finding.** The theory
has the right level and is too sensitive to volatility:

| Volatility tercile | empirical / analytical | β |
|---|---|---|
| Calm | 1.147 | **0.963** |
| Middle | 1.056 | **0.965** |
| Volatile | 0.944 | **0.753** |

**The deviation is entirely in the volatile tercile.** In calm and middle
markets β is within 4% of the prediction. `σ²/8` assumes continuous costless
arbitrage — close enough to true when prices move slowly, and false when gaps
open faster than arbitrageurs close them.

**The theory holds where its assumptions hold.**

*Figures: `h3_theory_vs_empirical.png`, `h3_by_regime.png`*

---

## 9 — H4: the fee-tier experiment ⚠️ *the premise was wrong*

H4 predicted higher tiers suffer proportionally less LVR, because arbitrage only
fires once the gap clears the fee. **They do not.**

**Derivation.** One arbitrage trade from gap `g` to fee `f` transfers
`(L√P/4)(g² − f²)`. The gap is a walk reflected at `±f`; local time accumulates
at `σ²/(2f)` and each unit transfers `(L√P/2)·f`. **The `f` cancels.** A wider
band makes arbitrage rarer and each event proportionally larger — exactly
offsetting.

**Confirmed numerically** (ratio → 1.0 at 15-min, 5-min, 1-min and 10-sec steps)
**and empirically:**

| Pool | fee | LVR per unit variance |
|---|---|---|
| 5bp | 5bp | 0.00553 |
| 30bp | 30bp | 0.00576 |
| 100bp | 100bp | 0.00590 |

A **20× fee range moves the slope 6.7%, t = +0.30** — and with the *opposite*
sign to the prediction.

**Two further problems with H4 as designed.** Uniswap bundles tick spacing with
fee tier (10/60/200), so the tiers cannot hold the same range; and the 100bp
pool has **no viable position size** — at $1,000 gas destroys it (−94.8%), at
$100k the position is 113% of the pool's active liquidity.

**H4 as written is not supportable.** The defensible replacement: *fee tier does
not affect LVR, only fee income, so the ranking is an empirical question about
volume rather than a theoretical one about adverse selection.*

*Figure: `fee_tier_lvr_flat.png`*

---

## 10 — Delta-hedged versus unhedged

| Pool | market-making | 95% CI | unhedged total | 95% CI | CI ratio |
|---|---|---|---|---|---|
| 5bp | −9.10% | [−15.6%, −3.3%] | −8.35% | [−46.3%, +30.0%] | **6.2×** |
| 30bp | −2.31% | [−5.2%, +1.3%] | −0.29% | [−36.6%, +32.6%] | **10.6×** |

**Hedging isolates the signal.** The unhedged interval is six to ten times
wider — leading with it would mean reporting a number whose error bar dwarfs it.

**And it sharpens the message.** The 30bp unhedged return is −0.29%, essentially
break-even, but only because a +2.02% directional gain offset a −2.31%
market-making loss.

> **LPs who made money made it from holding ETH, not from providing liquidity.**

---

## 11 — H5: is net return forecastable? ❌

| Model | RMSE | OOS R² |
|---|---|---|
| Mean baseline | 0.00531 | −0.003 |
| LightGBM | 0.00563 | **−0.128** |

Diebold-Mariano **favours the baseline**, p = 0.024. Gradient boosting is
significantly worse than predicting the historical mean.

The feature importances look economically sensible — vol-of-vol, position value,
trade count. **That is the trap**: plausible importances on a model with
negative out-of-sample R² mean nothing.

---

## 12 — H6: theory versus machine learning ⭐⭐

Same purged folds, same 352 observations.

| Model | RMSE | OOS R² | directional |
|---|---|---|---|
| **σ²/8 + HAR-RV** | **1,347.90** | **+0.126** | **0.742** |
| Mean baseline | 1,510.49 | −0.097 | 0.500 |
| LightGBM | 1,610.67 | −0.247 | 0.565 |
| σ²/8 + persistence | 1,668.10 | −0.338 | 0.724 |

**Diebold-Mariano, theory against LightGBM: p < 0.0001.** Not a tie.

The closed form is the **only model with positive out-of-sample R²**, beats the
baseline by 11% and LightGBM by 19%, and calls direction 74% of the time against
57%.

**The asymmetry is the explanation: one parameter fixed by derivation against
hundreds fitted on 366 observations.** On a sample this small the model that
cannot overfit wins, and it cannot overfit because its structure came from
economics rather than from the data.

The volatility model earns its place too — HAR-RV beats persistence by 19%.

---

## 13 — H7: the strategy ⚠️ *the signal works, the activity does not*

Engine: predict the **components**, not the total. LVR from the closed form
(R² +0.126), fees from LightGBM (R² +0.084) — each beats its own baseline where
the combined target scores −0.128.

| Strategy | ann. return | Sharpe | max DD | invested | DSR |
|---|---|---|---|---|---|
| **Strategy (net > 0.2%/wk)** | **−4.0%** | −1.35 | −12.3% | 55.7% | 0.000 |
| Equal-weight LP (passive) | −6.4% | −2.12 | −19.4% | 100% | 0.000 |
| Hold 50/50 tokens | **+8.2%** | 0.22 | −48.9% | 100% | 0.163 |

The strategy beats passive LP by **+2.46% annualised, t = 2.75, p = 0.0066**,
cuts drawdown by a third, and sits in cash 44% of weeks. **The forecast
genuinely identifies when not to provide.**

It cannot make an unprofitable activity profitable. **No strategy clears the
deflated Sharpe bar**, including both token benchmarks.

*Figure: `backtest_returns.png`*

---

## 14 — Robustness

**Range width** — 430 pool-months, monotone on both pools, **every CI excludes
zero**: −64.4% at ±2% to −1.8% at ±50% on the 5bp pool. The corner solution the
Stage 8 mathematics predicts when `κ < 0`.

**Subperiods** — the level match is stable every year (0.94–1.02); the slope is
not (β = 0.372 in 2023, 0.918 and 0.944 in 2024 and 2026). The full-sample
rejection of β = 1 is driven by 2023.

**MEV classification** — within the defensible range the estimate is $10.8M to
$12.8M, a **1.18× spread**. Outside it the classifier fails self-announcingly:
at 100% reversal tolerance total attacker "profit" is *negative*.

**Block alignment** — a reference one slot (12s) earlier **understates LVR by
18% on average, up to 31%**, because blocks cluster right after a price move and
a staler reference misses the move that triggered the trade. The effect scales
with sparsity: 12% on the dense 5bp pool, 25% on the sparse 30bp pool. This
vindicates the baseline — the arbitrageur *saw* that move.

*We closed this question once on one month, measured on the price gap, and got
it wrong. LVR is quadratic in the gap, so it is far more sensitive than the gap
itself. A robustness check has to run on the quantity being reported.*

**Hedge frequency** — weekly looks cheapest and is worst, leaving 15% of the
position in naked delta.

**Volatility estimator** — no estimator wins on every criterion. 5-minute RV has
the best level match (1.007); bipower the best slope, and its 1.085 ratio says
jumps transfer real value.

*Figures: `range_width_full_sample.png`, `mev_span_sensitivity.png`*

---

## 15 — What we do not claim

**Scope.** Mainnet only. ETH/USDC only — really 5bp versus 30bp, since the 100bp
pool has no viable size. Simulated positions, not observed ones.

**H4 is not supportable as written**, and we say so rather than reporting a
weak version of it.

**MEV magnitude is the least robust number here**, though attribution is neutral
so the decomposition does not rest on it.

**The strategy result is negative** and is reported as such. No configuration
clears the deflated Sharpe bar.

**What would falsify the central claim:** a pool where fees persistently exceed
LVR by more than costs. We found none in 86 pool-years, but two pools on one
asset is not a cross-section.

**Not established:** why 2023 behaves differently from later years; whether the
result generalises beyond ETH/USDC; whether L2 economics differ.

---

## Appendix

**A1 — Optimal range width.** `net(δ) = κ/δ − Aσ²/δ²`, `δ* = 2Aσ²/κ`, matching a
grid search to 0.02%. **Concentration is sign-neutral**: fees and LVR both scale
as `1/δ`, so range width sets the scale of an outcome and never its sign.
Confirmed empirically — the fee/LVR ratio moves 1.85% across a 34× span of
widths.

**A2 — Capacity.** Two floors: the tick grid and fee saturation. The grid binds
**20× before** capacity for a $100k position; capacity binds above ~$2M.

**A3 — The nine defects the gates caught.**

| # | Defect | How it announced itself |
|---|---|---|
| 1 | int24 ticks read at declared width (ABI sign-extends) | tick −2 decoded as a 78-digit number |
| 2 | pandas inferred int64 from the data | a quiet month would overflow above 9.22 WETH |
| 3 | Fees lost at the range boundary | −1.88% vs the contract, localised to one swap |
| 4 | Sandwich classifier mostly false positives | 45% of "sandwiches" lost money |
| 5 | Fee share ignored the position's own liquidity | flipped 100bp from +34.7% to −43.1% |
| 6 | HAR trained on labels past the forecast origin | caught by my own leak test |
| 7 | Headline mislabelled "raw" when it was hedged | "hedged" series had *higher* volatility |
| 8 | MEV span measured in `log_index` | a span of 4 found zero sandwiches |
| 9 | Q3 closed on a proxy quantity, one month | full sample moved LVR 18%, not 2bp |

**A4 — Every open question, closed.** All seven, with evidence, in
`DECISIONS.md`.

**A5 — Published queries.** `dune/*.sql`, plus the RPC client that replaced them
and why.
