# The True Cost of Providing Liquidity
**LVR, MEV, and the net return to Uniswap v3 market making**

15 slides + appendix. Every number traces to a table in `outputs/tables/` and
every figure to `scripts/make_figures.py`. `scripts/audit_deck.py` checks each
quoted figure against its source table and fails on drift.

---

## 1 — Title

**The True Cost of Providing Liquidity**
LVR, MEV, and the net return to Uniswap v3 market making

Repo · 10.4M swaps · 43 months · 5 pools · 3 asset pairs · 257 tests

> *Speaker note.* The one-line claim: liquidity provision pays exactly when fee
> income covers adverse selection, and whether it does is governed by volatility
> through a closed form. On ETH/USDC it does not. On a stablecoin pair it does,
> sixfold.

---

## 2 — Motivation: an AMM has no oracle

A pool prices from a formula, not a feed. It has no idea what ETH costs on
Binance and no mechanism to find out. **Its price updates only when someone
trades against it**, so after any move on a centralised venue it is stale.

Nobody is paid to fix this. Searchers do it as a side effect of making money:
buy the underpriced side from the pool, sell on Binance. That money comes out of
the LP.

**This is LVR: a systematic transfer from passive liquidity providers to
informed arbitrageurs, on every meaningful price move, permanently.**

---

## 3 — Who pays, and why nobody notices

| Flow | Informed? | Effect on the LP |
|---|---|---|
| Arbitrageurs | Yes, by construction | **Loses money** — they trade precisely when the pool is wrong |
| Retail swappers | No | **Makes money** — they pay fees and leave |

LVR is an **opportunity cost, not a line item**. No transaction is labelled
"arbitrageur took $400 from you". It shows up only as your position being worth
less than a continuously rebalanced portfolio would have been.

Every dashboard shows fees earned. None shows this.

---

## 4 — LVR is not impermanent loss

| | Compares against | Measures |
|---|---|---|
| **Impermanent loss** | Holding the two tokens | The cost of the AMM's rebalancing |
| **LVR** | A continuously rebalanced portfolio with the same delta | The cost of being *stale* |

**And this has a consequence used throughout.** From
`AMM_return = rebalanced_return + fees − LVR`, the quantity `fees − LVR` is
*already delta-hedged by construction*. That identity is the spine of the
decomposition — and it is what makes `fees/LVR` the only ratio that matters.

---

## 5 — Data and construction

| Source | What | Scale |
|---|---|---|
| Ethereum archive RPC (`eth_getLogs`) | Uniswap v3 swaps | **10.4M swaps**, 43 months, 5 pools |
| Binance bulk dumps | 1s klines, perp klines, funding | ETHUSDT, ETHBTC, USDCUSDT, BTCUSDT |
| Deribit public API | DVOL implied volatility | 44 months |
| Pool contracts (`eth_call`) | TVL, `feeGrowthInside`, tick state | historical blocks |

**Total cost: €0. No API keys.**

**Universe — chosen to span volatility, not just fee tiers:**

| Pool | pair | median annualised σ |
|---|---|---|
| USDC/USDT 1bp | a peg | **2.3%** |
| WBTC/ETH 30bp | a cross of two majors | **28.3%** |
| ETH/USDC 5 / 30 / 100bp | a major against the dollar | **52–53%** |

A **23× spread in volatility, 528× in variance** — which is what LVR scales with.

---

## 6 — H1: does the reconstruction hold up? ✅

| Gate | Criterion | Result |
|---|---|---|
| Stage 1 | price inside the 1bp band implied by the pool's own tick | **0 of 9,959 outside** |
| Stage 1 | `slot0()` at historical blocks matches the logs | **10/10 exact** |
| Stage 2 | fee replay within 2% of the contract's `feeGrowthInside` | **+0.18% / −0.52%** |
| Stage 3 | LVR positive, plausible, same order as theory | **all four checks** |
| Stage 6 | purged CV demonstrably closes a leak | **pass, both directions** |

**Eleven defects were caught by these gates**, every one producing plausible
numbers rather than errors. The list is in the appendix — it is the main
evidence the pipeline is sound.

---

## 7 — H2: the decomposition ⭐⭐

43 monthly cohorts per pool, $100k at ±10%, re-centred on exit. `fees − LVR − gas`,
already delta-hedged by the identity on slide 4.

| Pool | σ | fees | LVR | **fees/LVR** | **net** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|---|
| **USDC/USDT 1bp** | **2.3%** | +10.3% | −1.6% | **6.49** | **+8.43%** | **[+5.0%, +11.6%]** | **83%** |
| **PAXG/USDC 5bp** | **19.5%** | +17.2% | −18.5% | 0.93 | **−1.82%** | [−6.2%, +3.4%] | 50% |
| WBTC/ETH 30bp | 28.3% | +32.8% | −31.5% | 1.04 | +0.71% | [−1.6%, +3.4%] | 44% |
| **WBTC/USDC 30bp** | **40.0%** | +61.1% | −56.3% | 1.09 | **+4.09%** | [−0.5%, +9.0%] | 47% |
| ETH/USDC 5bp | 52.3% | +88.8% | −96.8% | 0.92 | −9.10% | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | 52.4% | +96.7% | −97.9% | 0.99 | −2.31% | [−5.2%, +1.3%] | 21% |

**Liquidity provision is not uniformly loss-making.** Two of five pools pay.
This falsified our own stated test: an earlier version claimed no pool had fees
exceeding LVR in 86 pool-years. Extending the universe found one, then a second.

### But volatility is not the mechanism — and the sixth pool is why

WBTC/USDC earns **+4.09% at 40% σ**, more than WBTC/ETH's +0.71% at 28% σ. If
volatility ranked pools that could not happen. Three things follow, and each
weakens the tidy version of this slide:

- `corr(σ, net)` is **−0.569** across seven pools (−0.730 on the six fitted),
  not the −0.923 an earlier four-pool version reported.
- Fitting `net = a + b·σ²` on 229 pool-months puts the crossover at **σ\* = 41.7%
  with a 95% CI of [30.4%, 77.3%] and R² = 0.048**. There is no well-determined
  crossover, and the decile curve is not monotone.
- **Within** a pool the slope on σ² is **+0.049, CI [−0.251, +0.379]**. The sign
  flips and it cannot be distinguished from zero — a Simpson's paradox.

> The cross-pool pattern is a statement about **which pools happen to be
> volatile**, not about what volatility does to a given pool.

**The old mechanism was wrong.** We claimed LVR scales with σ² while fee income
does not. In this sample both do, at nearly the same rate — volume rises with
volatility:

```
fees = +0.041 + 3.07·σ²   R² = 0.845
LVR  = +0.001 + 3.25·σ²   R² = 0.921
```

Net is the small difference between two large, near-parallel terms, which is
exactly why its R² is 0.048.

### Then a seventh pool falsified the replacement too ⭐

We had said `LVR/σ²` is 3.10–3.46 off the peg, so "does this pool pay?" reduces
to "is `fees/σ²` above ~3.3?" — which ranked five pools perfectly. **It had never
been tested between 2.3% and 28.3% σ, because nothing lived there.**

| pool | median σ | `LVR/σ²` |
|---|---|---|
| USDC/USDT 1bp | 2.3% | **41.82** |
| **PAXG/USDC 5bp** | **19.5%** | **5.23** |
| WBTC/ETH 30bp | 28.3% | 3.10 |
| WBTC/USDC 30bp | 40.0% | 3.32 |
| ETH/USDC 30bp | 52.4% | 3.34 |
| ETH/USDC 5bp | 52.3% | 3.46 |

Gold at 19.5% σ returns **5.23**, clears a 3.3 fee threshold (3.41), and still
**loses money**. Spearman falls **+1.000 → +0.829**.

> **Not a constant with one exception — one declining curve that flattens above
> ~28%.** The adverse-selection floor is present at every volatility and merely
> becomes small next to the diffusive term once σ is high enough. Same shape as
> the H3 bias curve on slide 8, on a different quantity — we now treat them as
> one phenomenon.

A threshold rule is valid **only above ~28% annualised**; below it the threshold
is pool-specific and the rule is a tautology. It is also partly mechanical, and
lagged one month does **not** beat the naive rule (76.2% vs 78.6%).

*(ETH/USDC 100bp withheld: a $100k position is 113% of its active liquidity.)*

*Figure: `crossover_profitability.png`*

---

## 8 — H3: does σ²/8 hold? ⭐

7,675 pool-days across six pools, empirical LVR on analytical, Newey-West errors.

| Pool | σ | β | R² | p(β=1) | level match |
|---|---|---|---|---|---|
| USDC/USDT 1bp | 2.3% | 0.634 | **0.002** | 0.000 | **6.60** |
| **PAXG/USDC 5bp** | **19.5%** | 0.718 | 0.208 | **0.121** | **1.064** |
| **WBTC/ETH 30bp** | 28.3% | **0.956** | **0.628** | **0.644** | **1.031** |
| WBTC/USDC 30bp | 40.0% | 0.666 | 0.487 | 0.007 | **1.015** |
| ETH/USDC 5bp | 52.3% | 0.784 | 0.618 | 0.015 | 0.972 |
| ETH/USDC 30bp | 52.4% | 0.838 | 0.620 | 0.143 | 1.011 |

**Where it works it works well** — around 62% of daily variation explained with
**zero fitted parameters**, and on WBTC/ETH the null β = 1 cannot be rejected.

### The bias is monotone in volatility — one curve, not a list of exceptions

| σ bucket | median σ | realised / predicted |
|---|---|---|
| q1 | 0.024 | **2.09** |
| q2 | 0.293 | 1.17 |
| q3 | 0.450 | 1.07 |
| p75–90 | 0.610 | 1.03 |
| p90–99 | 0.852 | 0.96 |
| top 1% | 1.465 | **0.76** |

> **σ²/8 under-predicts in calm markets, is unbiased around σ ≈ 0.6–0.9, and
> over-predicts in extreme ones.** The peg (6.6× on the pool, 2.09 here) and the
> crash days are the two ends of the same curve, not separate failures.

At low σ the diffusive term vanishes and exposes a **floor of adverse
selection** — discrete blocks, jumps, MEV-ordered flow — that the theory does
not model. At extreme σ it over-charges.

### This also disposes of the "2023 anomaly"

β was 0.372 in 2023 against 0.918–0.944 later. It is **two days**, not a year:
2023Q3 has β = 0.130, its top five day-pool cells are 35.8% of the quarter's
analytical LVR at a ratio of 0.182, and all five fall on **17–18 August 2023**.
Drop the top 1% of σ days and 2023 moves to 0.779 while the spread across years
collapses. The aggregate 2023 ratio is 0.958, so the level was never wrong.

### Four mechanisms tested, four refused — and the fourth is informative

| hypothesis | result |
|---|---|
| no-arbitrage fee band | **no** — β is *higher*, not lower, at low σ/fee |
| jumps | **no** — bipower moves 2023 β 0.372 → 0.381 |
| oversampling | **no** — variance *deflates* at fine sampling |
| range exhaustion | **no — and backwards** |

Splitting the most volatile days by the *shape* of the move at matched variance:
days that **leave** the ±10% range score **1.261**; days that stay inside and
merely oscillate score **0.780**. Trend coefficient **+0.252, CI [+0.212,
+0.294]**, P(coef < 0) = 0.000.

> **The over-prediction is on days that travel a long way without going
> anywhere.** A pool can be arbitraged at most once per block, and movement below
> the round-trip cost is never arbitraged, so oscillation produces realised
> variance no arbitrageur can convert into profit. Direction is captured in full.

*Stated as the surviving account, not a demonstration: per-block extraction is
not measured.*

*Figures: `h3_theory_vs_empirical.png`, `h3_by_regime.png`, `lvr_bias_by_sigma.png`*

---

## 9 — H4: the fee-tier experiment ❌ *the premise was wrong*

H4 predicted higher tiers suffer proportionally less LVR because arbitrage only
fires once the gap clears the fee. **They do not.**

**Derivation.** One arbitrage trade from gap `g` to fee `f` transfers
`(L√P/4)(g² − f²)`. The gap is a walk reflected at `±f`; local time accumulates
at `σ²/(2f)` and each unit transfers `(L√P/2)·f`. **The `f` cancels.**

**Confirmed numerically** (ratio → 1.0 at four step sizes) **and empirically:**

| Pool | fee | LVR per unit variance |
|---|---|---|
| ETH/USDC 5bp | 5bp | 0.00553 |
| ETH/USDC 30bp | 30bp | 0.00576 |
| WBTC/ETH 30bp | 30bp | 0.00660 |
| ETH/USDC 100bp | 100bp | 0.00590 |

A **20× fee range moves the slope 1.19×**, t = +0.30, with the *opposite* sign
to the prediction.

**Two further problems.** Uniswap bundles tick spacing with fee tier
(10/60/200), so the tiers cannot hold the same range; and the 100bp pool has no
viable position size at all.

**H4 as written is not supportable.** The replacement: *fee tier does not affect
LVR, only fee income — the ranking is an empirical question about volume, not a
theoretical one about adverse selection.*

*Figure: `fee_tier_lvr_flat.png`*

---

## 10 — Delta-hedged versus unhedged

| Pool | market-making | 95% CI | unhedged total | 95% CI | CI ratio |
|---|---|---|---|---|---|
| ETH/USDC 5bp | −9.10% | [−15.6%, −3.3%] | −8.35% | [−46.3%, +30.0%] | **6.2×** |
| ETH/USDC 30bp | −2.31% | [−5.2%, +1.3%] | −0.29% | [−36.6%, +32.6%] | **10.6×** |

**Hedging isolates the signal** — the unhedged interval is six to ten times
wider.

**And it sharpens the message.** The 30bp unhedged return is −0.29%, essentially
break-even, but only because a +2.02% directional gain offset a −2.31%
market-making loss.

> **LPs on ETH/USDC who made money made it from holding ETH, not from providing
> liquidity.**

---

## 11 — H5: is net return forecastable? ❌

| Model | RMSE | OOS R² |
|---|---|---|
| Mean baseline | 0.00531 | −0.003 |
| LightGBM | 0.00563 | **−0.128** |

Diebold-Mariano **favours the baseline**, p = 0.024. The feature importances
look economically sensible — vol-of-vol, position value, trade count. **That is
the trap**: plausible importances on a model with negative out-of-sample R² mean
nothing.

---

## 12 — H6: theory versus machine learning ⭐⭐

Same purged folds, same 352 observations.

| Model | RMSE | OOS R² | directional |
|---|---|---|---|
| **σ²/8 + HAR-RV** | **1,347.90** | **+0.126** | **0.742** |
| Mean baseline | 1,510.49 | −0.097 | 0.500 |
| LightGBM | 1,610.67 | −0.247 | 0.565 |

**Diebold-Mariano, theory against LightGBM: p < 0.0001.** The closed form is the
**only model with positive out-of-sample R²**.

**One parameter fixed by derivation against hundreds fitted on 366
observations.** On a sample this small the model that cannot overfit wins — and
it cannot overfit because its structure came from economics, not from the data.

---

## 13 — H7: the strategy ❌ *the rule does not survive either*

Five pools (100bp excluded for capacity), weekly, full costs, out-of-sample,
165 weeks. **Oracle rows removed — they are a ceiling, not a strategy.**

| Strategy | ann. return | Sharpe | max DD | deflated p |
|---|---|---|---|---|
| Always USDC/USDT 1bp | +6.4% | 1.96 | −3.4% | 0.83 |
| Always WBTC/USDC 30bp | +3.9% | 0.88 | −5.7% | 0.75 |
| Our forecast (calibrated) | +1.5% | 0.36 | −5.0% | 0.20 |
| Passive equal-weight | −0.3% | −0.15 | −3.3% | 0.03 |
| Always ETH/USDC 5bp | −10.1% | −2.59 | −27.4% | 0.00 |

**Nothing clears the 0.95 bar.** The model captures 11% of the available edge.

*For scale, the oracle ceiling — perfect foresight, not a strategy — is **+14.6% at Sharpe 3.96** on the four-pool universe and +17.3% at Sharpe 3.71 with WBTC/USDC added. Being forced to allocate every week rather than holding cash costs only 0.4pp, because the oracle is almost never out.*

### The static rule was the last positive claim, and it fails three tests

An earlier version of this deck recommended *"always hold the lowest-σ pool"* at
+6.4% and Sharpe 1.96. That number is **not implementable** — it is "always hold
USDC/USDT", a pool chosen with hindsight, before gas. Selecting on **lagged**
volatility and charging gas gives **+4.31% at Sharpe 1.39**.

**1. It is measured against zero, not cash.** The Sharpe here is `mean/sd` with
no risk-free rate, while the position ties up real capital. Against the
**realised 4-week Treasury bill** (4.62% over these weeks, from the
Treasury's own daily series):

| benchmark | excess ann. | Sharpe | deflated p |
|---|---|---|---|
| zero | +4.31% | 1.39 | 0.699 |
| **realised T-bill** | **-0.31%** | **-0.10** | **0.039** |
| flat 4% | +0.31% | 0.10 | 0.082 |
| flat 5% | −0.69% | −0.22 | 0.023 |

**It does not merely fail the bar — it loses to Treasury bills.**

**2. It is not a volatility rule.** Down the σ ladder: rank 1 **+4.3%**, rank 2
**−1.2%**, rank 3 **+2.6%**, rank 4 **−6.2%**. The second-lowest-σ pool loses
money. A mechanism would decay monotonically; this is pool selection.

**3. It is regime-dependent.** 2023: −1.0%, positive in 12.5% of weeks. First
half Sharpe 0.76, second half 2.66.

> **Retired.** The honest statement is *"the USDC/USDT pool paid well in
> 2024–2026 before financing costs"* — a description of one pool in one regime.

**What survives is the negative result, and it is a real one:** the edge is not
in forecasting volatility. Replacing each component with its own oracle shows
perfect variance forecasting is worth **0.9pp** and perfect fee forecasting
**11.4pp — 80% of the gap to the ceiling.** σ²/8 predicts the cost side well and
says nothing about the income side, and the income side is where the uncertainty
lives. **This is a volume-forecasting problem wearing a volatility costume.**

*Figures: `backtest_returns.png`, `static_rule.png`*

---

## 14 — Robustness

**Range width** — 430 pool-months, monotone on both pools, **every CI excludes
zero**: −64.4% at ±2% to −1.8% at ±50%. The corner solution Stage 8 predicts
when `κ < 0`.

**Subperiods** — the level match is stable every year (0.94–1.02); the slope is
not (β = 0.372 in 2023, 0.918–0.944 in 2024–26).

**Volatility regimes within ETH/USDC** — β = 0.963 and 0.965 in calm and middle
markets against 0.753 in the volatile one. **The cross-section confirms this
independently:** WBTC/ETH at half the volatility has the β closest to 1. Two
independent cuts agree σ²/8 degrades with volatility and nothing else.

**Block alignment** — a 12s-staler reference **understates LVR by 18%, up to
31%**, because blocks cluster right after a price move. *We closed this question
once on one month using the price gap and got it wrong; LVR is quadratic in the
gap. A robustness check must run on the quantity being reported.*

**MEV classification** — within the defensible range, $10.8M–$12.8M, a 1.18×
spread. Outside it the classifier fails self-announcingly: at 100% tolerance
total attacker "profit" is *negative*.

**Volatility estimator** — 5-minute RV has the best level match (1.007); bipower
the best slope, and its 1.085 ratio says jumps transfer real value.

---

## 15 — What we do not claim

**Scope.** Mainnet only. Simulated positions, not observed ones. Six pools,
three asset pairs and a peg — enough to show that a single-variable story does
not survive, not enough to replace it.

**Three of seven hypotheses are negative and reported as such.** H4's premise
was wrong, H5 does not forecast, H7's rule does not survive costs.

**The central mechanism was retracted mid-project.** We claimed LVR scales with
σ² while fee income does not. Both scale with σ², at nearly the same rate. What
we retained was that `LVR/σ²` is near-constant off the
peg, so pools differ in **fee income per unit variance**, not in volatility
as such.

**`corr(σ, net)` is between-pool only.** Within pools the slope's CI spans zero.
Nothing here licenses a causal reading of volatility on LP profitability.

**The crossover is not located.** σ\* = 43.5% with a CI of [32.2%, 76.2%] and
R² = 0.055. We report the interval, not the point.

**σ²/8 has a measured bias curve, not a single domain.** Realised/predicted runs
2.09 → 0.76 monotonically in σ. We do not model the floor at the low end.

**MEV magnitude is the least robust number here**, though attribution is neutral
so the decomposition does not rest on it. We now have an independent check:
blocks where the classifier finds a sandwich carry **7.0× the
builder→proposer payment** of blocks with a swap and none (95% CI
[5.7, 8.6]) — market-set
confirmation the classifier finds real extraction. Our attributed profit is
101% of that payment, which is economics
rather than validation: our estimate is **gross of the searcher's own bid**, and
the payment *is* that bid, so parity is what a competitive auction predicts.
**The count is still a lower bound; the profit is mostly paid onward to the
proposer, not kept by the searcher.**

**Still open:** what happens on extreme-volatility days (range exhaustion is the
leading candidate, untested); whether `fees/σ²` is forecastable at all; whether
L2 economics differ.

**What already falsified the replacement:** a pool whose `LVR/σ²` sits far from ~3.3
without being a peg, or a demonstration that `fees/σ²` is predictable a month
ahead — which would convert the one negative result we are most confident in.

---

## Appendix

**A1 — Optimal range width.** `net(δ) = κ/δ − Aσ²/δ²`, `δ* = 2Aσ²/κ`, matching a
grid search to 0.02%. **Concentration is sign-neutral**: fees and LVR both scale
as `1/δ`, so range width sets the scale of an outcome and never its sign — the
fee/LVR ratio does. Confirmed empirically: that ratio moves 1.85% across a 34×
span of widths.

**A2 — Capacity.** Two floors: the tick grid and fee saturation. The grid binds
**20× before** capacity at $100k; capacity binds above ~$2M.

**A3 — The eleven defects the gates caught.**

| # | Defect | How it announced itself |
|---|---|---|
| 1 | int24 ticks read at declared width (ABI sign-extends) | tick −2 decoded as a 78-digit number |
| 2 | pandas inferred int64 from the data | a quiet month would overflow above 9.22 WETH |
| 3 | Fees lost at the range boundary | −1.88% vs the contract, localised to one swap |
| 4 | Sandwich classifier mostly false positives | 45% of "sandwiches" lost money |
| 5 | Fee share ignored the position's own liquidity | flipped 100bp from +34.7% to −43.1% |
| 6 | HAR trained on labels past the forecast origin | caught by our own leak test |
| 7 | Headline mislabelled "raw" when it was hedged | "hedged" series had *higher* volatility |
| 8 | MEV span measured in `log_index` | a span of 4 found zero sandwiches |
| 9 | Q3 closed on a proxy quantity, one month | full sample moved LVR 18%, not 2bp |
| 10 | Hedge shorted ETH against a USDC delta | funding of −9,856% of notional |
| 11 | Raw σ²/8 used as a forecast, inheriting its bias | model ranked the worst pools first |

**A4 — All seven open questions closed**, with evidence, in `DECISIONS.md`.

**A5 — Published queries.** `dune/*.sql`, plus the RPC client that replaced them
and why.
