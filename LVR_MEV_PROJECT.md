# The True Cost of Providing Liquidity
**LVR, MEV, and the Net Return to Uniswap v3 Market Making**

Project specification — WUTIS Algorithmic Trading application
Companion paper to *Flow-Based Dealer Gamma in Crypto Options*

---

## 1. Thesis

> Advertised AMM yields are gross of two systematic costs that liquidity providers actually pay: loss-versus-rebalancing, the profit arbitrageurs extract because AMM prices lag centralised venues, and MEV extraction through transaction ordering. We decompose the realised return to Uniswap v3 liquidity provision into fees, LVR, MEV and gas; test the closed-form LVR prediction against observed arbitrage flows; and build a pool-selection strategy that provides liquidity only where fee income exceeds these costs.

---

## 2. Background

### What an AMM is

A pool holds two assets. Price is set by a formula, not an order book. The classic constant-product rule:

```
x · y = k
```

Buy asset x from the pool and x falls, y rises, and the next unit costs more. The formula quotes continuously without any counterparty.

**Liquidity providers (LPs)** deposit both assets and earn a pro-rata share of trading fees. They are the market makers; the formula quotes on their behalf.

### The structural flaw

An AMM has **no price oracle**. It has no idea what ETH costs on Binance and no mechanism to find out. Its price updates only when someone trades against it.

So after any move on a centralised venue, the pool is stale — quoting the old price.

### Who corrects it, and at whose expense

Nobody is paid to rebalance. Independent **searchers** — professional bot operators competing on latency and gas bids — monitor the gap and trade it when it exceeds gas plus fee. They buy the underpriced side from the pool and sell on Binance.

The correction is a side effect of someone making money. That money comes out of the LP, who sold too cheap or bought too dear because the pool was stale.

**This is LVR: a systematic transfer from passive liquidity providers to informed arbitrageurs, on every meaningful price move, permanently.** It is structural, not a bug. As long as an AMM prices from a formula rather than a feed, it will always be stale after a move.

### Why nobody accounts for it

LVR is an **opportunity cost, not a line item.** No transaction is labelled "arbitrageur took $400 from you." It appears only as your position being worth less than a continuously rebalanced portfolio would have been. Every dashboard shows fees earned. None shows this.

A large pool of capital — retail LPs, DAO treasuries, yield vaults — is therefore systematically mispricing its own returns.

### The theoretical anchor

Milionis, Moallemi, Roughgarden & Zhang (2022) derive that for a constant-product AMM, the arbitrageur's rate of profit is proportional to

```
σ² / 8
```

per unit of pool value per unit time.

**This is unusually valuable: a closed-form theoretical prediction that can be tested against observed data.** Most ML-in-finance papers fit a model and report R². This one checks whether reality matches a derivation.

### Adverse selection, stated properly

| Flow type | Informed? | Effect on LP |
| --- | --- | --- |
| Arbitrageurs | Yes, by construction | **Loses money** — they trade precisely when the pool is wrong |
| Retail swappers | No | **Makes money** — they pay fees and leave |
| Aggregator routing | Mixed | Neutral to slightly negative |
| Protocol/liquidation flow | Mixed | Neutral |

The real question the paper answers:

> **In which pools does uninformed flow outweigh arbitrage flow?**

This is the same adverse-selection problem every market maker faces. It maps directly onto the companion GEX paper — a Deribit dealer earning spread from retail while being picked off by informed flow is doing the identical thing. The difference is that Deribit dealers hedge and model it carefully; most Uniswap LPs do not know it is happening.

---

## 3. Research questions

1. What is the realised net return to Uniswap v3 liquidity provision, after LVR, MEV and gas?
2. Does the σ²/8 closed form match empirically observed arbitrage extraction?
3. Can net return be forecast well enough to allocate across pools profitably?
4. Does the closed-form LVR forecast beat a machine-learning forecast?

---

## 4. Hypotheses

### H1 — The decomposition is computable ⚠️ GO/NO-GO

LP position value, fee accrual, arbitrage extraction and MEV can be reconstructed from public on-chain data with acceptable error.

**Validation:** reconstructed pool state must match the subgraph's reported TVL and fee totals. Report the error distribution.

### H2 — Advertised yields systematically overstate returns

**Prediction:** net return is materially below advertised APR across pools, and negative in a meaningful subset — particularly low-fee tiers on volatile pairs.

**Test:** the decomposition table (§7, Output 1) across pools and time.

### H3 — The σ²/8 prediction holds ⭐ core theoretical contribution

**Prediction:** analytically computed LVR (from CEX realized volatility) tracks empirically observed arbitrage extraction.

**Test:** regress empirical LVR on analytical LVR. Report slope, R², and where they diverge. **The gap is itself the finding** — it quantifies how much of the theory survives real gas costs, discrete blocks, and fee-tier frictions.

### H4 — Fee tier is the dominant determinant of net profitability

**Prediction:** on the same pair, higher fee tiers earn less gross but suffer proportionally less LVR (arbitrage only fires when the gap exceeds the fee), and may be net superior.

**Test:** ETH/USDC at 5bp / 30bp / 100bp is a clean natural experiment — same asset, same volatility, different fee. Compare net returns.

### H5 — Net return is forecastable

**Test:** gradient boosting on pool characteristics predicting next-period net return. Purged, embargoed cross-validation.

### H6 — Theory beats ML on the LVR component ⭐

**Prediction:** the σ²/8 closed form, fed a volatility forecast, outperforms gradient boosting at predicting LVR.

**Test:** head-to-head, out-of-sample.

**Why this matters:** theory outperforming a black box is a rarer and stronger result than the reverse, and it signals genuine understanding rather than fashion.

### H7 — Economic significance

**Test:** weekly allocation strategy, full costs. Benchmarks: equal-weight LP, hold tokens, 50/50 rebalanced.

**Permitted to fail.** "LP returns are negative in most pools once fully accounted" is a legitimate and arguably more interesting finding than a profitable strategy.

---

## 5. Data

**Total cost: €0.**

| Data | Source | Purpose |
| --- | --- | --- |
| Uniswap v3 swaps, mints, burns, pool state, tick liquidity | **Dune Analytics** (free SQL over Ethereum) — `uniswap_v3_ethereum.Pool_evt_Swap`, `Pool_evt_Mint`, `Pool_evt_Burn` | LP position reconstruction, fee accrual |
| Block ordering, builder payments, bundles | **Flashbots** relay data; `mev-inspect`; Dune MEV tables | MEV attribution |
| Reference CEX price | **Binance / Coinbase** tick data (free) | LVR — the external price LVR is defined against |
| Pool metadata, fee tiers, TVL | **Uniswap subgraph** (The Graph, free tier) | Universe construction, validation |
| Gas prices | On-chain / Etherscan | Cost accounting |
| Perp funding rates | Binance / Deribit public API | Delta-hedged variant (§6.5) |

> **Implementation note.** The on-chain half of this table was substituted for
> raw `eth_getLogs` against public Ethereum archive RPCs during Stage 1. See
> `DECISIONS.md` 0.4 for the reasoning and what would reverse it.

### Universe

**Core:** ETH/USDC at 5bp, 30bp, 100bp — the natural experiment for H4.

**Extension:** WBTC/ETH 30bp, USDC/USDT 1bp, plus 2–3 volatile pairs for cross-sectional variation.

Keep it small. Depth of analysis over breadth of universe.

### Sample period

**2023-01-01 → 2025-12-31.** Covers varied volatility regimes and the post-Merge MEV-Boost era, so builder data is consistent throughout.

---

## 6. Method

### 6.1 Reconstruct the LP position

Simulate depositing a fixed notional at time T. Track block-by-block from swap data:

- position value (both legs, at pool price)
- cumulative fee accrual
- for v3: whether the position remains in range

### 6.2 Compute LVR two ways

**Analytically:**

```
LVR_rate = σ² / 8   (per unit pool value, per unit time)
```

σ from Binance realized volatility over the interval.

**Empirically:** at each block, compare pool price to CEX price. The gap is what an arbitrageur could extract. Sum realised extraction across the period.

**H3 is the comparison of these two series.**

### 6.3 Identify MEV

Classify sandwich attacks from within-block ordering: a victim swap bracketed by two swaps from the same searcher address. Cross-check against Dune's pre-classified MEV tables and Flashbots bundle data. Attribute extracted value.

### 6.4 Assemble the decomposition

```
net_return = fees − LVR − MEV − gas
```

### 6.5 The delta-neutrality decision ⚠️ DECIDE IN WEEK 1

Raw LP means being long both assets. That return is dominated by whether ETH went up, which swamps everything being measured.

| Variant | What it measures | Verdict |
| --- | --- | --- |
| **Raw LP** | Market-making return + directional beta | Realistic but noisy |
| **Delta-hedged** | Pure market-making return: fees − LVR − MEV − funding | **Preferred** — isolates the contribution |

Report both. Lead with delta-hedged, because that is what the paper is actually about. This choice changes every table; settle it before building.

### 6.6 Forecast model

```
Features (known at t)                Target
──────────────────────────           ─────────────────
realized vol, trailing 7d            net LP return
implied vol / DVOL                   over t+1 week
fee tier
volume / TVL ratio
liquidity concentration
tick spacing
historical MEV intensity
gas price level
pool age, TVL
```

Gradient boosting (LightGBM). **Purged, embargoed cross-validation** — overlapping weekly targets will otherwise produce a fake R².

**Baseline to beat (H6):** analytical σ²/8 with a HAR-RV or GARCH volatility forecast.

### 6.7 Original mathematics — optimal range width

Uniswap v3 permits concentrating liquidity in a price range. Narrow range → more fees per dollar deployed, but more LVR per dollar and the position falls out of range on a move.

**Solve for the range width maximising expected net return under an LVR cost.** A real optimisation with a real answer, and the appendix slide demonstrating capability beyond running gradient boosting.

---

## 7. Outputs

### Output 1 — Decomposition table (the headline finding)

| Pool | Fee tier | Advertised APR | Fees | LVR | MEV | Gas | **Net** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ETH/USDC | 5bp | 18.2% | +18.2% | −22.4% | −0.9% | −0.4% | **−5.5%** |
| ETH/USDC | 30bp | 9.1% | +9.1% | −6.2% | −0.3% | −0.4% | **+2.2%** |
| ETH/USDC | 100bp | 4.3% | +4.3% | −1.8% | −0.1% | −0.4% | **+2.0%** |
| WBTC/ETH | 30bp | 11.4% | +11.4% | −13.1% | −0.5% | −0.4% | **−2.6%** |

*Illustrative structure — numbers are placeholders, not results.*

If low-fee tiers prove systematically loss-making while high-fee tiers do not, that is a clean, quantified finding that directly contradicts what LPs are shown.

### Output 2 — Allocation signal

```
timestamp: 2025-03-14
pool: ETH/USDC-30bp
predicted_fee_yield:   +8.4%   (annualised)
predicted_LVR:         −5.1%
predicted_MEV:         −0.3%
predicted_net:         +3.0%
signal:                 PROVIDE
weight:                 0.35
```

| Pool | Predicted net | Signal | Weight |
| --- | --- | --- | --- |
| ETH/USDC 30bp | +3.0% | PROVIDE | 0.35 |
| ETH/USDC 100bp | +2.1% | PROVIDE | 0.25 |
| USDC/USDT 1bp | +1.8% | PROVIDE | 0.40 |
| ETH/USDC 5bp | −4.2% | AVOID | 0.00 |
| WBTC/ETH 30bp | −1.9% | AVOID | 0.00 |

Not a buy/sell signal — an allocation decision about where to park LP capital.

### Output 3 — Backtest

|  | Strategy | Equal-weight LP | Hold tokens | 50/50 rebalanced |
| --- | --- | --- | --- | --- |
| Annualised return |  |  |  |  |
| Volatility |  |  |  |  |
| Sharpe |  |  |  |  |
| Max drawdown |  |  |  |  |
| Turnover |  |  |  |  |

**Benchmark honesty:** "hold tokens" will usually beat the strategy on raw return in a bull market. The claim is risk-adjusted. State that plainly rather than hiding it.

---

## 8. Known limitations — state explicitly

1. **LVR ≠ impermanent loss.** IL compares to holding; LVR compares to a continuously rebalanced portfolio. These are routinely conflated. Getting the distinction right and explaining it clearly is worth its own slide and signals real engagement with the literature.
2. **Block-level price alignment is a modelling choice.** Ethereum blocks are ~12s; Binance ticks are continuous. The matching rule is defensible but not obvious, and must be documented with alternatives tested.
3. **MEV classification is heuristic.** Sandwich detection has false positives and negatives. Report sensitivity to the classification rule.
4. **Mainnet only.** L2 deployments (Arbitrum, Base) have different gas economics and MEV structure. Scope stated, not hidden.
5. **Simulated LP position.** You are reconstructing what a position would have earned, not observing an actual one. Path-dependence of v3 range management is approximated.
6. **Retrospective universe selection.** Pools chosen with knowledge of which existed and remained liquid. Acknowledge the survivorship dimension.

---

## 9. Statistical standards

| Requirement | Implementation |
| --- | --- |
| Cross-validation | **Purged and embargoed** — overlapping weekly targets otherwise inflate R² |
| Multiple testing | **Deflated Sharpe Ratio**; log every specification tried |
| Out-of-sample | Split declared in methods before results |
| Costs | Gas, swap fees, rebalancing — from the first backtest, never appended |
| Uncertainty | Confidence intervals on every estimate |
| Reproducibility | Fixed seeds, config file, every figure regenerable by script |
| Transparency | Public repo, all Dune queries published |

---

## 10. Deck structure (15 slides + appendix)

| # | Slide | Content |
| --- | --- | --- |
| 1 | Title | + repo link |
| 2 | Motivation | What an AMM is; why it has no oracle; the staleness problem in one diagram |
| 3 | Who pays | Arbitrageur vs retail flow; adverse selection framing |
| 4 | LVR vs impermanent loss | The distinction, stated precisely |
| 5 | Data & construction | Sources, universe, sample, filters, obs surviving each |
| 6 | H1 — Reconstruction validation | Reconstructed vs subgraph TVL and fees |
| 7 | **H2 — The decomposition table** | Headline. Advertised vs actual |
| 8 | **H3 — Does σ²/8 hold?** | Analytical vs empirical LVR, scatter + regression |
| 9 | H4 — Fee tier experiment | ETH/USDC 5/30/100bp side by side |
| 10 | Delta-hedged vs raw | Isolating the market-making return |
| 11 | H5 — Forecast model | Feature importance, out-of-sample fit |
| 12 | **H6 — Theory vs ML** | Head-to-head on LVR prediction |
| 13 | H7 — Strategy backtest | Net of costs, deflated Sharpe |
| 14 | Robustness | Alternative MEV rules, block alignment, subperiods |
| 15 | **What we do not claim** | Limitations, what would falsify |
| A1+ | Appendix | Optimal range-width derivation, full tables, Dune queries |

---

## 11. Timeline (4 weeks)

### Week 1 — Data layer (the bottleneck)

- [x] **Decide delta-neutral vs raw. This changes everything downstream.**
- [x] Learn the on-chain schema; write and validate swap/mint/burn queries
- [x] Pull Binance tick data for the reference price
- [x] Reconstruct one pool's state for one month
- [x] **H1 validation: does the reconstruction hold up? GO/NO-GO**

### Week 2 — Decomposition

- [ ] Fee accrual for a simulated position
- [ ] Empirical LVR from block-level price gaps
- [ ] Analytical LVR from realized vol
- [ ] **H3: do they agree?**
- [ ] MEV classification

### Week 3 — Modelling

- [ ] Full decomposition table across the universe (H2, H4)
- [ ] Feature engineering, gradient boosting (H5)
- [ ] **H6 horse race: σ²/8 vs ML**

### Week 4 — Delivery

- [ ] Strategy backtest with full costs, deflated Sharpe (H7)
- [ ] Optimal range-width derivation (appendix)
- [ ] Robustness battery
- [ ] Deck, repo, README

---

## 12. Risk register

| Risk | Prob. | Mitigation |
| --- | --- | --- |
| **Data source learning curve eats week 1** | **High** | Budget it explicitly. Start with one pool, one month |
| Reconstruction doesn't validate | Medium | Narrow to a single pool; debug against known state before scaling |
| MEV classification unreliable | Medium | Use Dune's pre-classified tables as primary, own classifier as robustness |
| Gas costs kill the strategy | **High** | Include from the first backtest. If they dominate, that IS the finding — report it |
| Scope creep to L2s / more pools | High | Mainnet, small universe. Cut extensions first |
| Delta decision made late | Medium | **Force it in week 1** |

---

## 13. Positioning within the programme

Three papers, one theme — **who is actually paying whom, and does the headline number reflect it.**

| Paper | Venue | Question |
| --- | --- | --- |
| **Dealer gamma** | Crypto options (Deribit) | Does dealer hedging flow move spot, and can it be observed directly? |
| **This paper** | On-chain AMM (Uniswap v3) | Is advertised LP yield real once adverse selection is priced? |
| **Generative simulators** | Equities | Is a single-path backtest a defensible way to evaluate either of the above? |

Framing: *"Three studies of market microstructure — derivatives, on-chain, and methodology."*

Both this paper and the GEX paper study a market maker earning spread while being adversely selected. The difference is sophistication: Deribit dealers hedge and model it; most Uniswap LPs do not know it is happening. That parallel is worth one sentence in each deck.

---

## 14. References

- Milionis, Moallemi, Roughgarden & Zhang (2022). *Automated Market Making and Loss-Versus-Rebalancing.*
- Milionis, Moallemi & Roughgarden. *A Myersonian Framework for Optimal Liquidity Provision in AMMs.*
- Adams et al. *Uniswap v3 Core* (whitepaper).
- Daian et al. *Flash Boys 2.0: Frontrunning, Transaction Reordering, and Consensus Instability in DEXs.*
- Barbon & Ranaldo. *On The Quality Of Cryptocurrency Markets: CEX vs DEX.*
- Bailey & López de Prado. *The Deflated Sharpe Ratio.*
- López de Prado. *Advances in Financial Machine Learning* (purged CV).
- Dune docs: docs.dune.com
- Flashbots data: docs.flashbots.net
