# The True Cost of Providing Liquidity in Uniswap v3

**LVR, MEV and the net return to concentrated-liquidity market making.**
Yehor Vasylchenko, University of Vienna. Working paper:
[`outputs/paper/LVR_MEV_WorkingPaper.pdf`](outputs/paper/LVR_MEV_WorkingPaper.pdf).

An AMM liquidity provider is a passive market maker quoting a deterministic
curve against informed flow. Its advertised fee APR is gross of the two costs a
market maker actually pays: **adverse selection**, which in an AMM takes the
form of loss-versus-rebalancing (LVR), and **toxic order flow** routed through
block ordering (MEV). This repository reconstructs a $100k position per block
from raw swap logs across seven pools and 43 months, decomposes its realised
return as

```
net = fees − LVR − MEV adjustment − gas − perp funding
```

tests the closed-form LVR prediction `σ²/8` against the observed series, and
backtests a pool-allocation rule with full costs against a realised cash rate.

Everything is a gate: a stage whose output fails its sanity check stops the
pipeline rather than producing a slide. 266 tests, 40 stage scripts, one config.

---

## Data

| Series | Source | Volume |
|---|---|---|
| Uniswap v3 `Swap` events | `eth_getLogs` on public Ethereum archive RPC, decoded in-house | 11.2M swaps, 7 pools, 2023-01 → 2026-07 |
| Reference price | Binance 1-second klines (`data.binance.vision`) | 9.4 GB |
| Perp funding, mark | Binance USD-M monthly dumps | per 8h epoch |
| Implied vol | Deribit DVOL | daily |
| Gas | Block header `baseFeePerGas` | per block |
| Fee accounting truth | `feeGrowthGlobal`, `feeGrowthOutside` via `eth_call` at historical blocks | per cohort |
| MEV market price | Flashbots relay `proposer_payload_delivered` | 5,000 blocks |
| Cash rate | US Treasury 4-week bill, daily XML | per business day |

Logs are decoded from hex rather than read from a warehouse because
`sqrtPriceX96` is a `uint160` and `liquidity` a `uint128`: both exceed int64,
and a SQL numeric or parquet round-trip is where a silent float coercion enters.
`logIndex` gives the exact within-block ordering that sandwich detection needs.
Cost of the data: zero, no API keys. Seven pools: ETH/USDC at 5 and 30 bp,
WBTC/USDC 30 bp, WBTC/ETH 30 bp, PAXG/USDC 5 bp, USDC/USDT 1 bp, spanning
2.3% to 52% realised volatility.

---

## Pipeline

### 1. Pool state, exact arithmetic

Price is derived from `sqrtPriceX96` as `(sqrtPriceX96 / 2^96)^2 · 10^(d0−d1)`
in `Decimal` with 50-digit precision; no float touches the price path. The
`tick` field emitted on the same event is held back and used only as an
independent cross-check (`P = 1.0001^tick`, round-trip exact). Signed ABI fields
are decoded at 256 bits and range-checked; big integers persist as strings and
load as `object` dtype. The integer `TickMath` port and the `Decimal` path are
independent implementations of the same function and test against each other.

### 2. Causal alignment of a continuous venue to a 12-second block grid

LVR is defined against an external price, so the alignment rule *is* the
definition of staleness. A 1-second kline for second `s` covers `[s, s+1)` and
its close may be timestamped after `s`; matching the kline at the block time `T`
admits up to one second of lookahead. The baseline matches the latest kline with
`s ≤ T − 1`: strictly causal, with staleness known and bounded at one second.
The property is asserted by test, not assumed.

Three rules are swept (`at-or-before`, `one slot earlier`, `midpoint
interpolation`, the last flagged as non-causal). Pool-minus-CEX gap on
ETH/USDC:

| Pool | mean \|gap\| | p95 \|gap\| | fee |
|---|---|---|---|
| 5 bp | 4.2 bp | 8.9 bp | 5 bp |
| 30 bp | 22.6 bp | 33.6 bp | 30 bp |

The pool sits inside its own no-arbitrage band: the gap is of the order of the
fee, which is the mechanism the fee-tier model in §9 is built on.

### 3. Position

$100k, symmetric ±10% band around entry, re-centred on range exit, one cohort
per calendar month (43 per pool, independent entry points). Token amounts are
exact integers in base units from the v3 amount function; the position's risky
delta is `∂V/∂S` of that function evaluated at the pool price, not 0.5.
Sweeps: half-width {2, 5, 10, 25, 50}%, re-centre {never, on exit, weekly},
notional {10k, 100k, 1M, 10M} for capacity.

### 4. Fees, accrued only in range and validated against the contract

Fees accrue per swap, pro-rata to the position's share of active liquidity at
the current tick, and only while the tick is inside the range. The replay is
validated against the contract's own accounting,
`fees = L · ΔfeeGrowthInside / 2^128`, read with four `eth_call`s at the entry
and exit blocks. Agreement on the gate month: 0.18% (token0), 0.52% (token1)
against a 1% tolerance. The `feeGrowthOutside` epoch reset on tick
re-initialisation is detected and the exact method abstains rather than
returning a wrong difference.

### 5. LVR, three measures

LVR is the P&L gap between the AMM position and a continuously rebalanced
portfolio holding the same delta. It is not impermanent loss (which compares to
holding) and not arbitrageur profit (which is LVR net of fees and gas).

- `lvr_from_cex_path`: what the position loses if arbitraged to the CEX price
  every block. Depends only on the external path. This is the quantity `σ²/8`
  predicts and is what the theory is tested against.
- `lvr_from_pool_path`: what the position actually lost from the pool price
  moving, marked at the contemporaneous external price. Negative on blocks
  where uninformed flow pushes the pool *away* from the external price, which
  is the LP being paid.
- `analytical_lvr_rate`: `(σ²/2) · S² · |dn/dS|` with the v3 amount function,
  which gives `σ² · L · √P / 4` in range and `σ²V/8` for a full-range pool. The
  v3 form handles range boundaries where `|dn/dS| → 0`.

The gap between the first two is the frictional wedge: arbitrage fires only
when the gap clears fee plus gas, so the pool is not continuously corrected.

### 6. MEV, classified within the block and priced by the builder market

Sandwiches are matched on `logIndex` order inside a block: `A (addr, dir D) →
victim (dir D) → C (same addr, −D)`, with the back leg required to unwind the
front within a reversal tolerance (swept 2% to 100%) and strictly positive
searcher profit. Attribution to the LP is worked leg by leg: the LP does a
round trip, earns three fees instead of one, and ends near the inventory the
victim alone would have left. The direct cost is small and positive; the
measured quantity is therefore sandwich *intensity* as a flow-quality covariate,
reported under three treatments (exclude attacker legs, neutral, toxic).

Validation uses a price the classifier never saw: the builder→proposer payment
from the Flashbots relay. Blocks containing a detected sandwich command
**7.0× the payment** of blocks with a swap in the same pool and no sandwich
(block-bootstrap 95% CI [5.7, 8.6]).

### 7. Delta hedge on the perpetual, with every cost measured

Binance ETH perpetual, hourly rebalance (daily and weekly swept), hedge ratio
from the position's own delta, 4 bp taker fee per rebalance, funding at the
exchange's published 8-hour rate. Hedging error between rebalances is measured
rather than assumed; it is the open question that decides whether the hedged
variant is the cleaner one. Gas is charged at the block's actual base fee for
entry, exit and every re-centre, never at a period average, because averages
understate cost in exactly the high-gas regimes that squeeze a strategy.

### 8. Volatility estimation and the theory test

Realised variance from 5-minute log returns over a trailing 24h is the
baseline; 1-minute RV, bipower variation and Garman-Klass are raced on the same
days. 1-minute sampling has the highest R² but the lowest β (microstructure
noise inflates σ²); bipower, which strips jumps the diffusion result does not
cover, has β closest to one.

Daily empirical LVR is regressed on the daily analytical rate,
`LVR_emp = α + β · LVR_σ²/8 + ε`, prediction `β = 1`:

| Sample | n (pool-days) | β | 95% CI | R² |
|---|---|---|---|---|
| ETH/USDC 5 bp + 30 bp, pooled | 2,613 | 0.81 | [0.67, 0.95] | 0.62 |
| WBTC/ETH 30 bp | 1,305 | 0.96 | [0.77, 1.14] | 0.63 |
| USDC/USDT 1 bp | 1,238 | 0.63 | [0.54, 0.73] | 0.00 |

Realised over predicted LVR runs monotonically from 1.98 at the peg to 0.76 in
the top volatility percentile: an adverse-selection floor the diffusion model
omits dominates at low σ, and the model over-predicts in jump regimes. `LVR/σ²`
is one declining curve (41.8 at 2.3% σ, 5.2 at 19.5%, 3.1 to 3.5 above 28%),
not a constant.

### 9. Closed-form theory

**Optimal range width.** In log price under driftless Brownian motion with a
band of half-width δ re-centred on exit: fee rate `F/δ`, LVR rate `σ²/(4δ)`,
exit rate `σ²/δ²` from `E[τ] = δ²/σ²`, so re-centring gas enters as
`(g/V)·σ²/δ²`. Two constraints the naive optimum omits: tick spacing bounds δ
from below, and fee income saturates when the position dominates active
liquidity. The in-range LVR rate is validated against the block-level
implementation: 20.1% predicted vs 20.8% measured.

**Optimal fee tier.** The pool-CEX gap `g = log(S/P)` is a random walk reflected
at `±f`; each reflection transfers `(L√P/4)(g² − f²)` to arbitrageurs. The
frictionless limit `f = 0` recovers `σ²L√P/4` exactly, asserted by test. The
uninformed-volume elasticity is not derivable and is carried as an explicit
parameter with the result's sensitivity to it.

### 10. Forecasting without leakage

Weekly panel, target = next week's net return per pool. Every feature is known
at `t`; `assert_no_lookahead` is a gate. Cross-validation is purged (training
rows whose target window overlaps the test fold are dropped) and embargoed (a
further 7 days after the fold), because overlapping weekly targets otherwise
manufacture out-of-sample R². Every specification tried is appended to a log as
it runs, so the deflated Sharpe ratio uses a prospective trial count.

LVR arm, identical folds, 352 out-of-sample pool-weeks:

| Model | RMSE | OOS R² | direction |
|---|---|---|---|
| `σ²/8` with HAR-RV variance forecast | 1,348 | **+0.126** | 74% |
| historical mean | 1,510 | −0.097 | 50% |
| LightGBM | 1,611 | −0.247 | 57% |

Diebold-Mariano on squared errors: the one-parameter closed form beats the
boosted model at p < 10⁻⁴. Predicting net return directly is worse than the
mean; predicting the components with their own best model (closed form for
LVR, LightGBM on volume and liquidity features for fees, OOS R² +0.083) is what
produces a usable signal.

### 11. Allocation backtest

Weekly rebalance across pools on `predicted_fees − predicted_LVR − gas`. Costs
from the first run: gas for entry, exit and re-centring is inside each pool's
weekly return, and a switch adds an entry and an exit. Benchmarks: equal
weight, 50/50 rebalanced, hold tokens, ex-post best pool (oracle). Every
Sharpe is reported raw and deflated; excess return is against the realised
4-week T-bill, forward-filled from the last business day at or before each
week end.

| Rule | ann. return | Sharpe | deflated |
|---|---|---|---|
| forecast allocation | +1.5% | 0.36 | 0.20 |
| static USDC/USDT | +6.4% | 1.96 | 0.83 |
| static USDC/USDT, excess over realised rf (4.62%) | −0.3% | −0.10 | 0.04 |
| ex-post oracle | +17.3% | 3.71 | |

Replacing each forecast component with its oracle: perfect variance forecasting
is worth 0.9 pp, perfect fee forecasting 11.4 pp. The allocation problem is a
volume-forecasting problem.

---

## Results

| Pool | median σ | fees | LVR | **net** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|
| USDC/USDT 1 bp | 2.3% | +10.3% | −1.6% | **+8.4%** | [+5.0, +11.6] | 83% |
| PAXG/USDC 5 bp | 19.5% | +17.2% | −18.5% | −1.8% | [−6.2, +3.4] | 50% |
| WBTC/ETH 30 bp | 28.3% | +32.8% | −31.5% | +0.7% | [−1.6, +3.4] | 44% |
| WBTC/USDC 30 bp | 40.0% | +61.1% | −56.3% | +4.1% | [−0.5, +9.0] | 47% |
| ETH/USDC 5 bp | 52.3% | +88.8% | −96.8% | −9.1% | [−15.6, −3.3] | 26% |
| ETH/USDC 30 bp | 52.4% | +96.7% | −97.9% | −2.3% | [−5.2, +1.3] | 21% |

Annualised, `fees − LVR − gas`, which is delta-hedged by construction since LVR
is defined against the rebalanced portfolio. Block-bootstrap CIs.

- Fees and LVR both scale with σ² at nearly the same slope
  (`fees = 0.043 + 3.06σ²`, `LVR = −0.003 + 3.26σ²`); net return is the small
  difference of two large terms.
- Volatility does not rank pools. Cross-pool `corr(σ, net) = −0.57`; within
  pools the fixed-effects slope is +0.05 with CI [−0.25, +0.38]. Simpson's
  paradox, not a tradeable rule.
- Fee tier does not reduce LVR per unit variance across a 100× fee range.
- No allocation rule clears a deflated-Sharpe bar against the realised cash
  rate. The information exists (oracle +17%); it is not forecastable from
  volatility.

Four earlier claims were falsified by later stages and are recorded with the
test that killed each in [`DECISIONS.md`](DECISIONS.md).

---

## Reproduce

```bash
pip install -e ".[dev]"
PYTHONPATH=. python3 scripts/reproduce.py          # tests, gates, audit on existing outputs
PYTHONPATH=. python3 scripts/reproduce.py --full   # rebuild from raw logs, ~2.5 h
PYTHONPATH=. python3 scripts/make_paper.py         # typeset the paper from the tables
```

Fixed seed, one `config.yaml`, every table and figure regenerated by script.
`scripts/audit_deck.py` pins every number in the deck and paper to its source
table and fails on drift.

```
config.yaml           every parameter that changes a table
DECISIONS.md          each modelling choice: what, why, what would reverse it
src/fetch/            rpc_client, binance_data, deribit, flashbots, gas, treasury
src/build/            pool_state, align, position, fees, lvr, mev, hedge, recentre, decomposition
src/model/            volatility (RV, BV, GK, HAR), features, purged_cv, forecast
src/strategy/         allocate, backtest
src/theory/           range_width, fee_tier
src/utils/            precision, stats (Newey-West, deflated Sharpe, block bootstrap), speclog
scripts/              one entry point per stage, reproduce.py runs them in order
tests/                266 tests, including the gates
dune/                 published SQL equivalents of every extraction
outputs/paper/        working paper, built by scripts/make_paper.py
```
