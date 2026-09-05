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

## Status

| Stage | Scope | State |
|---|---|---|
| 0 | Decisions: delta-hedged primary, position spec, universe, data source | **Settled** |
| 1 | Data layer: pool state, price reconstruction, CEX alignment | **Gate passed** |
| 2 | LP position reconstruction and fee accrual | Not started |
| 3 | LVR — empirical and analytical | Not started |
| 4 | MEV classification and attribution | Not started |
| 5 | Decomposition table (H2, H4) | Not started |
| 6 | Forecasting and the theory-vs-ML horse race (H5, H6) | Not started |
| 7 | Strategy backtest (H7) | Not started |
| 8 | Optimal range width (appendix) | Not started |

### Stage 1 results

Pool-versus-CEX price gap, ETH/USDC, January 2023, basis-corrected:

| Pool | blocks | mean abs gap | p95 abs gap | fee |
|---|---|---|---|---|
| ETH/USDC 5bp | 135,091 | 4.08 bp | **8.18 bp** | 5 bp |
| ETH/USDC 30bp | 9,959 | 22.99 bp | **33.63 bp** | 30 bp |

Each pool's p95 gap sits at roughly its own fee tier — the no-arbitrage band,
measured directly. This is the mechanism H4 rests on, confirmed before anything
is built on it.

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
