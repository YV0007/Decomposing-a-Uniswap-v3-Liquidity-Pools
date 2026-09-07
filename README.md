# The True Cost of Providing Liquidity

**LVR, MEV, and the net return to Uniswap v3 market making.**

Advertised AMM yields are gross of two systematic costs that liquidity
providers actually pay: **loss-versus-rebalancing**, the profit arbitrageurs
extract because AMM prices lag centralised venues, and **MEV** extraction
through transaction ordering. This repository decomposes the realised return to
Uniswap v3 liquidity provision into fees, LVR, MEV and gas; tests the
closed-form `sigma^2 / 8` LVR prediction against observed arbitrage flows; and
builds a pool-selection strategy that provides liquidity only where fee income
exceeds these costs.

Companion paper to *Flow-Based Dealer Gamma in Crypto Options*.

See [`LVR_MEV_PROJECT.md`](LVR_MEV_PROJECT.md) for the research design and
[`DECISIONS.md`](DECISIONS.md) for every modelling choice, its reasoning, and
what would reverse it.

---

## Headline result

43 monthly cohorts per pool, 2023-01 to 2026-07, $100k at ±10%, re-centred on
range exit. `fees − LVR − gas`, which is already delta-hedged because LVR is
defined against a continuously rebalanced portfolio.

| Pool | median σ | fees | LVR | **fees/LVR** | **net** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|---|
| **USDC/USDT 1bp** | **2.3%** | +10.3% | −1.6% | **6.49** | **+8.43%** | **[+5.0%, +11.6%]** | **83%** |
| WBTC/ETH 30bp | 28.3% | +32.8% | −31.5% | 1.04 | +0.71% | [−1.6%, +3.4%] | 44% |
| ETH/USDC 5bp | 52.3% | +88.8% | −96.8% | 0.92 | −9.10% | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | 52.4% | +96.7% | −97.9% | 0.99 | −2.31% | [−5.2%, +1.3%] | 21% |

> **Liquidity provision pays exactly when fee income covers adverse selection,
> and whether it does is governed by volatility.** `corr(σ, net) = −0.923`. The
> crossover sits between 28% and 52% annualised.

The mechanism is the closed form this project set out to test: **LVR scales with
σ², fee income does not.** Double the volatility and adverse selection
quadruples while fees rise far less.

*This falsified our own stated test.* An earlier version of this README claimed
LPs lose money and that no pool had fees exceeding LVR in 86 pool-years.
Extending the universe beyond ETH/USDC found one, and the claim did not survive.

### The four results worth reading

**σ²/8 works, and its failure is informative.** Across 3,842 pool-days the closed
form explains **62% of daily LVR variation with no fitted parameters** and
predicts the aggregate three-and-a-half-year transfer to within **1%**. On
WBTC/ETH — an independent asset pair — the null β = 1 cannot be rejected at all
(p = 0.644). On the 2.3%-volatility peg it fails completely (R² 0.002, realised
LVR 6.6× predicted), because the diffusive term vanishes and exposes a floor the
theory does not model. **The closed form has a measured domain of validity.**

**Theory beats machine learning.** On identical purged folds, σ²/8 with a HAR-RV
variance forecast is the only model with positive out-of-sample R² (+0.126),
beating LightGBM by 19% on RMSE at **p < 0.0001**. One parameter fixed by
derivation against hundreds fitted on 366 observations.

**A fee band does not reduce LVR.** H4's premise is false, by derivation and by
measurement. Across a 20× fee range, LVR per unit variance moves 6.7% with
t = +0.30 — and the opposite sign to the prediction.

**A static rule beats the model sixtyfold.** Always providing to the
lowest-volatility pool earns +6.4% at Sharpe 1.96; the forecast-driven weekly
allocation earns +0.1%. The rule is not fitted — it follows from the table
above. *The actionable conclusion is a rule, not a model.*

## Status — complete

| Stage | Scope | State |
|---|---|---|
| 0–5 | Decisions, data, position, fees, LVR, MEV, decomposition | ✅ gated |
| 6–7 | Forecasting, theory-vs-ML, allocation | ✅ |
| 8 | Optimal range width | ✅ |
| — | Robustness; all 7 open questions | ✅ closed |
| — | Cross-section: 3 asset pairs, 23× volatility range | ✅ |

| Hypothesis | Verdict |
|---|---|
| H1 the decomposition is computable | ✅ every gate passed |
| H2 advertised yields overstate returns | ✅ confirmed, and qualified |
| H3 σ²/8 holds | ✅ where its assumptions hold; **fails below ~28% σ** |
| H4 fee tier is the dominant determinant | ❌ **premise falsified** |
| H5 net return is forecastable | ❌ worse than the mean |
| H6 theory beats ML on LVR | ✅ **p < 0.0001** |
| H7 economic significance | ⚠️ a profitable rule exists; **our forecast does not find it** |

## Quickstart

```bash
pip install -e ".[dev]"
```

```bash
PYTHONPATH=. python3 -m pytest tests/ -q
```

Verify every pool address, token ordering and decimal count against the chain:

```bash
PYTHONPATH=. python3 scripts/verify_pools.py
```

Reconstruct one pool's state for one month and run the Stage 1 gate:

```bash
PYTHONPATH=. python3 scripts/stage1_pool_state.py
```

Align the CEX reference and measure the price gap:

```bash
PYTHONPATH=. python3 scripts/stage1b_alignment.py
```

---

## Data

Total cost: **EUR 0**. No API keys.

| Data | Source | Purpose |
|---|---|---|
| Uniswap v3 swaps, pool state | `eth_getLogs` against public Ethereum archive RPC | Position reconstruction, fee accrual |
| Reference CEX price | Binance 1s klines via `data.binance.vision` | The external price LVR is defined against |
| Perp funding | Binance futures monthly dumps | Delta-hedged variant |
| Pool metadata | Read directly from the pool contract | Universe construction, verification |
| MEV classification | Flashbots relay; Dune pre-classified tables | MEV attribution |

On-chain data comes from raw logs rather than Dune: event fields arrive as
canonical hex integers with no intermediary decoding, `logIndex` gives the exact
within-block ordering MEV classification needs, and the same query can be
replayed against several independent providers as a cross-check. The Dune
queries in [`dune/`](dune/) are published as the readable statement of what is
extracted. Reasoning in `DECISIONS.md` 0.4.

---

## Precision

`src/utils/precision.py` exists because `sqrtPriceX96` is a uint160 and does not
survive float64. A silent 1e-8 relative error in the price path compounds
through the LVR sum into a number that looks plausible and is wrong.

| Item | Requirement | Failure mode |
|---|---|---|
| `sqrtPriceX96` | Integer/Decimal only until the final division | Silent price error, compounds in LVR |
| Token decimals | USDC 6, WETH 18, WBTC 8 — verified per pool on-chain | Price off by 10^12 |
| token0/token1 | Address-sorted, verified per pool on-chain | Price inverted |
| Signed ABI fields | Decode at 256 bits, range-check afterwards | int24 tick decodes to a 78-digit number |
| Persistence | Big integers stored as strings, loaded to `object` dtype | int64 overflow above 9.22 WETH |
| Tick <-> price | `P = 1.0001^tick`, round-trip exact | Range boundaries wrong |
| CEX alignment | Latest kline with `s <= T - 1` | Up to 1s of lookahead |

The integer TickMath port and the Decimal path are independent implementations
of the same function and cross-check each other, so a mistyped magic constant
fails a test rather than shifting a price.

---

## Layout

```
├── config.yaml            every number that changes a table
├── DECISIONS.md           Stage 0 choices, open questions, defects found
├── dune/                  published SQL
├── data/{raw,interim,processed}/
├── src/
│   ├── fetch/    rpc_client, binance_data, subgraph, flashbots, gas
│   ├── build/    pool_state, align, position, fees, lvr, mev, hedge, decomposition
│   ├── model/    volatility, features, purged_cv, forecast
│   ├── strategy/ allocate, backtest
│   ├── theory/   range_width, fee_tier
│   └── utils/    precision, config, speclog, stats, plotting
├── scripts/               one entry point per stage; every figure regenerable
├── tests/
└── outputs/{figures,tables}/
```

---

## Standards

| Requirement | Implementation |
|---|---|
| Cross-validation | Purged and embargoed — overlapping weekly targets otherwise inflate R² |
| Multiple testing | Deflated Sharpe Ratio; every specification logged as it is run |
| Out-of-sample | Split declared in methods before results |
| Costs | Gas, swap fees, rebalancing — from the first backtest, never appended |
| Uncertainty | Confidence intervals on every estimate |
| Reproducibility | Fixed seeds, one config file, every figure regenerable by script |
| Transparency | Public repo, all queries published, defects recorded in `DECISIONS.md` |

A negative result is permitted. "Advertised LP yields are systematically
overstated and the strategy does not recover them" is a legitimate finding, and
arguably a more interesting one than a profitable strategy.
