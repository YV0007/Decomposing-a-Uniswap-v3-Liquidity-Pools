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
range exit. All annualised, with block-bootstrap confidence intervals.

| Pool | fees | LVR | gas | **market-making** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|
| ETH/USDC 5bp | +88.84% | −96.77% | −1.17% | **−9.10%** | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | +96.72% | −97.90% | −1.14% | **−2.31%** | [−5.2%, +1.3%] | 21% |

**Fees covered 92% and 99% of adverse selection.** On the 30bp pool the unhedged
return was −0.29% — essentially break-even — but only because a +2.02%
directional gain offset a −2.31% market-making loss.

> **LPs who made money made it from holding ETH, not from providing liquidity.**

`fees − LVR` is *already delta-hedged*, because LVR is defined against a
continuously rebalanced portfolio. Its confidence interval is 6–11× tighter than
the unhedged return's.

### The three results worth reading

**σ²/8 works, and fails informatively.** Across 3,842 pool-days the closed form
explains **62% of daily LVR variation with no fitted parameters** and predicts
the aggregate three-and-a-half-year transfer to within **1%**. Its slope is
significantly below one — but only in the volatile tercile (β = 0.753 against
0.963 and 0.965 in calm and middle markets). The theory holds where its
assumptions hold.

**Theory beats machine learning.** On identical purged folds, σ²/8 with a HAR-RV
variance forecast is the only model with positive out-of-sample R² (+0.126),
beating LightGBM by 19% on RMSE at **p < 0.0001**. One parameter fixed by
derivation against hundreds fitted on 366 observations.

**A fee band does not reduce LVR.** H4's stated premise is false, by derivation
and by measurement. One arbitrage trade transfers `(L√P/4)(g² − f²)`; the gap is
a walk reflected at `±f` with local time `σ²/(2f)`; the `f` cancels. Measured
across a 20× fee range, LVR per unit variance moves 6.7% with t = +0.30.

## Status — complete

| Stage | Scope | State |
|---|---|---|
| 0 | Decisions, universe, data source | ✅ settled |
| 1 | Data layer, price reconstruction, alignment | ✅ gate passed |
| 2 | Position reconstruction and fee accrual | ✅ gate passed |
| 3 | LVR, empirical and analytical | ✅ gate passed |
| 4 | MEV classification and attribution | ✅ |
| 5 | Decomposition, full sample | ✅ |
| 6 | Forecasting, theory-vs-ML (H5, H6) | ✅ |
| 7 | Strategy backtest (H7) | ✅ |
| 8 | Optimal range width | ✅ |
| — | Robustness, all 7 open questions | ✅ closed |

| Hypothesis | Verdict |
|---|---|
| H1 the decomposition is computable | ✅ every gate passed |
| H2 advertised yields overstate returns | ✅ confirmed, and qualified |
| H3 σ²/8 holds | ✅ R² 0.618, level match 0.991 |
| H4 fee tier is the dominant determinant | ❌ **premise falsified** |
| H5 net return is forecastable | ❌ worse than the mean |
| H6 theory beats ML on LVR | ✅ **p < 0.0001** |
| H7 economic significance | ❌ negative, as permitted |

---

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
