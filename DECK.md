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
| WBTC/ETH 30bp | 28.3% | +32.8% | −31.5% | 1.04 | +0.71% | [−1.6%, +3.4%] | 44% |
| ETH/USDC 5bp | 52.3% | +88.8% | −96.8% | 0.92 | −9.10% | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | 52.4% | +96.7% | −97.9% | 0.99 | −2.31% | [−5.2%, +1.3%] | 21% |

> **`corr(σ, net return) = −0.923`.** Liquidity provision is profitable where
> volatility is low and loss-making where it is high. The crossover — where fees
> stop covering LVR — sits between 28% and 52% annualised.

**The mechanism is the theory: LVR scales with σ², fee income does not.** Double
volatility and adverse selection quadruples while fees rise far less.

*This falsified our own stated test. An earlier version of this deck claimed no
pool had fees exceeding LVR in 86 pool-years. Extending the universe found one.*

*(ETH/USDC 100bp withheld: a $100k position is 113% of its active liquidity.)*

---

## 8 — H3: does σ²/8 hold? ⭐

3,842 pool-days, empirical LVR on analytical, Newey-West errors.

| Pool | σ | β | R² | p(β=1) | level match |
|---|---|---|---|---|---|
| USDC/USDT 1bp | 2.3% | 0.634 | **0.002** | 0.000 | **6.60** |
| **WBTC/ETH 30bp** | 28.3% | **0.956** | **0.628** | **0.644** | **1.031** |
| ETH/USDC 5bp | 52.3% | 0.784 | 0.618 | 0.015 | 0.972 |
| ETH/USDC 30bp | 52.4% | 0.838 | 0.620 | 0.143 | 1.011 |

**Where it works it works well** — 62% of daily variation explained with **zero
fitted parameters**, and on WBTC/ETH the null β = 1 cannot be rejected at all.

**Where it fails, it fails informatively.** On the peg R² is 0.002 and realised
LVR is **6.6× the prediction**. That is not a broken pool: it is the diffusive
term vanishing and exposing a floor the theory does not model.

> **LVR = a diffusive part σ²/8 captures, plus a floor it does not.**
> Volatile pools: the first dominates, the theory works. A peg: the second
> dominates, and it fails sixfold.

**The closed form has a measured domain of validity: roughly 28–53% annualised.**

*Figures: `h3_theory_vs_empirical.png`, `h3_by_regime.png`*

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

## 13 — H7: the strategy ⚠️ *a static rule beats the model*

Four pools (100bp excluded for capacity), weekly, full costs, out-of-sample.

| Strategy | ann. return | Sharpe | max DD | deflated Sharpe |
|---|---|---|---|---|
| Oracle — perfect foresight | **+14.6%** | **3.96** | 0.0% | **passes** |
| **Static: always the lowest-σ pool** | **+6.4%** | **1.96** | −3.4% | 0.83 |
| Our forecast (calibrated) | +0.1% | 0.03 | −4.7% | 0.06 |
| Passive equal-weight | −1.4% | −0.68 | −5.1% | 0.00 |
| Always ETH/USDC 5bp | −10.1% | −2.59 | −27.4% | 0.00 |

**A static rule with no forecasting beats our model sixtyfold.** It captures 45%
of the available edge; the model captures 9%.

And the rule is not fitted — it falls out of slide 7: *provide where
`fees/LVR > 1`, which means provide where volatility is low.*

**The actionable conclusion is a rule, not a model.** Consistent with H5 and H6
throughout: the forecasting adds little, the theory adds a lot.

*Honest caveat: even the static rule scores 0.83 against a 0.95 deflated-Sharpe
bar with 10 logged specifications. Suggestive, not established.*

*Figure: `backtest_returns.png`*

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

**Scope.** Mainnet only. Simulated positions, not observed ones. Three asset
pairs — enough to establish that volatility governs the answer, not enough to
locate the crossover precisely.

**H4 is not supportable as written**, and we say so rather than reporting a weak
version of it. **H5 and H7 are negative** and reported as such.

**σ²/8 has a lower bound** — it fails entirely below roughly 28% annualised
volatility, and we do not model the floor that replaces it.

**MEV magnitude is the least robust number here**, though attribution is neutral
so the decomposition does not rest on it.

**Not established:** why 2023 behaves differently from later years; where
exactly the profitability crossover sits; whether L2 economics differ.

**What would falsify the central claim now:** a low-volatility pool where fees
persistently fail to cover LVR, or a high-volatility one where they do. The
claim is no longer "LPs lose money" — it is that `fees/LVR` decides it and
volatility decides `fees/LVR`.

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
