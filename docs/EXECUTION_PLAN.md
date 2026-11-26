# LVR/MEV — Execution Plan

**Companion to `LVR_MEV_PROJECT.md`. That document is the *what*; this is the *how*.**

Read `LVR_MEV_PROJECT.md` first. This plan assumes it.

---

## How to use this document

Each stage has: **objective**, **exact steps**, **precision requirements**, **acceptance criteria**, and **open questions**.

The open questions are deliberate. They mark places where the right approach is genuinely unsettled and where investigation should beat following instructions. If a better method is found, take it — and record the reasoning in `DECISIONS.md`.

The acceptance criteria are not deliberate. Do not proceed past a stage that fails them.

---

## Stage 0 — Decisions before any code

These three choices propagate into every table. Settle them in writing, in `DECISIONS.md`, before Stage 1.

### 0.1 Delta-neutral or raw? ⚠️

| Variant | Measures | Problem |
| --- | --- | --- |
| **Raw LP** | market-making return + directional beta | ETH's move swamps everything |
| **Delta-hedged** | fees − LVR − MEV − funding | requires a hedge model and funding data |

**Default: build delta-hedged as primary, raw as robustness.** The paper is about market-making economics, not ETH beta.

Hedge specification to fix now:

- Instrument: Binance or Deribit ETH perpetual
- Rebalance frequency: daily (baseline), hourly and weekly as alternatives
- Funding cost: actual realised funding, not an assumption
- Hedge ratio: LP position delta from the v3 position formula, not 0.5

**Open question:** v3 concentrated positions have path-dependent delta that changes as price moves through the range. Is a daily rebalance sufficient, or does the hedging error itself become material? Measure it rather than assuming.

### 0.2 Position specification

A "position" is not well defined until you fix:

- Notional (baseline $100,000)
- Range width — v3 requires choosing one. Baseline: ±10% around entry price
- Re-centring rule: never / on exit from range / weekly
- Entry timing: fixed cohorts (first of month) vs rolling

**Baseline: $100k, ±10%, re-centre on range exit, monthly cohorts.**

Every one of these is a config parameter with alternatives swept later.

### 0.3 Universe

**Core (required):** ETH/USDC 5bp, 30bp, 100bp — the H4 natural experiment.

**Extension (only after core works):** WBTC/ETH 30bp, USDC/USDT 1bp, one volatile pair.

Do not start with six pools. One pool, one month, end to end, before scaling anything.

---

## Stage 1 — Data layer (Week 1, the bottleneck)

### 1.1 Source setup

Queries live in `dune/` as `.sql` files in the repo — **publishing them is part of the transparency contribution.**

Core tables:

```
uniswap_v3_ethereum.Pool_evt_Swap
uniswap_v3_ethereum.Pool_evt_Mint
uniswap_v3_ethereum.Pool_evt_Burn
uniswap_v3_ethereum.Factory_evt_PoolCreated
ethereum.blocks
ethereum.transactions
```

Pool addresses (verify each against Etherscan before use):

- ETH/USDC 5bp — `0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`
- ETH/USDC 30bp — `0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8`
- ETH/USDC 100bp — `0x7bea39867e4169dbe237d55c8242a8f2fcdcc387`

**Fields required from `Pool_evt_Swap`:** `evt_block_number`, `evt_block_time`, `evt_tx_hash`, `evt_index`, `amount0`, `amount1`, `sqrtPriceX96`, `liquidity`, `tick`, `sender`, `recipient`

`evt_index` matters — it is the within-block ordering needed for MEV classification. Do not drop it.

> **Implemented as:** `eth_getLogs` against public Ethereum archive RPCs, with
> verification done by reading the pool contract directly rather than by
> reading a block explorer. See `DECISIONS.md` 0.4 and 0.5.

### 1.2 Price reconstruction — precision critical

Pool price comes from `sqrtPriceX96`:

```
price = (sqrtPriceX96 / 2^96)^2 × 10^(decimals0 - decimals1)
```

**Precision requirements — get these wrong and everything downstream is silently wrong:**

- `sqrtPriceX96` is a **uint160**. It overflows float64. Use Python `int` or `Decimal` throughout, never `float`, until the final division.
- USDC has 6 decimals, WETH has 18. The adjustment is not optional.
- Verify token0/token1 ordering per pool — it is address-sorted, not semantic. In ETH/USDC pools USDC is often token0, which inverts the price.
- Cross-check: take 10 random blocks, compute price, compare to an external reference for that block. **Must agree to within 0.1%.**

### 1.3 CEX reference price

Binance ETHUSDT trades or 1-second klines, 2023-01-01 → 2025-12-31, via their public data dumps (`data.binance.vision`) — free bulk download, no key.

**The alignment problem.** Ethereum blocks are ~12s; Binance is continuous. Baseline rule: **the last CEX trade at or before the block timestamp.** No forward-looking, ever.

**Open question:** block timestamps are proposer-set and can drift by seconds. Does using the parent block timestamp, or a mid-block interpolation, change LVR materially? Test it; if the answer is yes, that is a robustness slide.

### 1.4 Acceptance criteria — Stage 1 GO/NO-GO

- [x] Pool price reconstructed for ETH/USDC 30bp, one month, matching an independent reference on a 10-block spot check
- [x] No float64 anywhere in the sqrtPriceX96 path
- [x] token0/token1 ordering verified per pool
- [x] CEX series aligned with a documented, non-lookahead rule
- [x] Swap counts reconciled

**Do not proceed if the price reconstruction fails the check.**

---

## Stage 2 — LP position reconstruction (Week 1–2)

### 2.1 The v3 position

Unlike v2, liquidity is concentrated between ticks. Position value:

```
L = liquidity (constant while in range)

In range:
  amount0 = L × (1/√P − 1/√P_upper)
  amount1 = L × (√P − √P_lower)

Below range: entirely token0
Above range: entirely token1
```

Tick-to-price:

```
P = 1.0001^tick
```

**Precision:** ticks are integers, prices are not. Round-tripping tick → price → tick must be exact. Test it.

### 2.2 Fee accrual

Fees accrue **only while the position is in range**, pro-rata to the position's share of active liquidity at that tick.

```
fee_earned = swap_volume × fee_tier × (L_position / L_active_at_tick)
```

`L_active_at_tick` is the hard part — it is total liquidity spanning the current tick, which changes with every mint and burn anywhere in the range.

| Approach | Method | Trade-off |
| --- | --- | --- |
| **A — event replay** | Rebuild the full tick liquidity map from all Mint/Burn events since pool creation | Exact, expensive |
| **B — use pool state** | `liquidity` field on each Swap event is active liquidity at that moment | Cheap, sufficient if the position is small relative to the pool |

**Start with B.** A $100k position in a $200m pool barely moves the denominator. Validate against A on one week; if agreement is within 1%, keep B and document the choice.

**Open question:** at what position size does B break down? Worth quantifying — it determines the capacity of any strategy built on this.

### 2.3 Acceptance criteria

- [ ] Simulated position value tracks the pool's implied value with no drift
- [ ] Fee accrual for one month within 2% of the `feeGrowthGlobal`-derived figure
- [ ] In-range / out-of-range transitions occur at the correct tick boundaries
- [ ] Approach B validated against A on one week

---

## Stage 3 — LVR (Week 2) ⭐ core

### 3.1 Empirical LVR

The definition that matters: **LVR is the P&L difference between the AMM position and a continuously rebalanced portfolio holding the same instantaneous delta.**

Per block:

```
1. pool_price     ← from sqrtPriceX96
2. cex_price      ← aligned CEX reference
3. pool_delta     ← position's token0 holding
4. rebalanced_delta ← what a continuously-rebalanced portfolio would hold at cex_price
5. lvr_increment  ← (cex_price − pool_price) × (pool_delta − rebalanced_delta)
```

Sum across blocks.

**Common error to avoid:** LVR is *not* the sum of arbitrageur profits. Arbitrageur profit is LVR **minus fees paid minus gas**. LVR is the gross adverse selection; extraction is what survives frictions. Report both — the gap between them is informative and is part of H3.

### 3.2 Analytical LVR

```
LVR_rate = σ² / 8   per unit pool value per unit time
```

σ from CEX realized volatility. **Specify precisely:**

- Estimator: realized variance from 5-minute log returns (baseline)
- Window: trailing 24h
- Annualisation: √(365 × 24 × 12) for 5-min sampling
- Alternatives to sweep: 1-min RV, Garman-Klass, bipower variation

**Open question:** which volatility estimator best matches empirical LVR? This is itself a small research question. Microstructure noise argues for 5-min over 1-min; jumps argue for bipower. Test rather than assume.

### 3.3 H3 — the comparison

```
empirical_LVR(t) = α + β × analytical_LVR(t) + ε
```

**Prediction:** β ≈ 1, α ≈ 0.

Report: β with Newey-West standard errors, R², and residual analysis. Where does the theory break — high volatility, low liquidity, high gas?

**This is the paper's theoretical contribution. Give it its own slide regardless of outcome.**

### 3.4 Acceptance criteria

- [ ] Empirical LVR is positive on net (arbitrageurs profit from LPs — sign check)
- [ ] Magnitude is plausible: annualised LVR on ETH/USDC should be in the single-digit to low-double-digit percent range. If it comes back at 200% or 0.02%, something is wrong — say so rather than reporting it
- [ ] Analytical and empirical are the same order of magnitude
- [ ] LVR scales with realized volatility in the cross-section

---

## Stage 4 — MEV (Week 2–3)

### 4.1 Sandwich classification

Pattern: within one block, `evt_index` ordering shows

```
tx_A (searcher buys)  →  tx_B (victim swap)  →  tx_C (searcher sells)
```

with tx_A and tx_C from the same address, same pool, opposite directions.

**Baseline: use Dune's pre-classified MEV tables** (`mev.sandwiches` or similar — verify current schema). Own classifier as robustness.

**Precision:** searchers rotate addresses. Same-address matching undercounts. Bundle-level identification via Flashbots relay data catches more. Report both counts.

### 4.2 Attribution to the LP

Important distinction: **sandwiching primarily harms the trader, not the LP directly.** The LP earns fees on all three transactions.

The LP effect is indirect — sandwich flow is informed flow, which degrades the quality of the order flow the LP faces.

**Open question, and a genuine one:** what is the correct way to attribute MEV cost to LPs? Options include (a) excluding sandwich volume from "good" fee revenue, (b) treating it as neutral since fees are earned on it, (c) measuring the toxicity of the resulting flow. **Investigate the literature and pick a defensible answer. Document the reasoning — this is a real modelling decision, not a lookup.**

### 4.3 Acceptance criteria

- [ ] Sandwich count for a known-active period is within the same order of magnitude as published MEV dashboards
- [ ] Attribution method documented with explicit reasoning
- [ ] Results reported with and without MEV adjustment

---

## Stage 5 — Decomposition table (Week 3)

### 5.1 Assemble

```
net_return = fees − LVR − MEV_adjustment − gas − funding(if hedged)
```

All annualised, all per pool per period.

**Gas:** entry, exit, re-centring events, hedge rebalances. Use actual historical gas prices at those blocks, not an average.

### 5.2 H4 — fee tier experiment

ETH/USDC at 5bp / 30bp / 100bp. Same asset, same volatility, different fee.

**Prediction:** higher tiers earn less gross but suffer proportionally less LVR, because arbitrage only fires when the price gap exceeds the fee. Net ranking is an empirical question.

**Open question:** is there an optimal fee tier as a function of volatility? If so, that is a clean theoretical result worth deriving.

### 5.3 Acceptance criteria

- [ ] Table populated for all core pools, full sample
- [ ] Advertised APR included as the comparison column
- [ ] Signs and magnitudes sanity-checked
- [ ] Both raw and delta-hedged variants reported

---

## Stage 6 — Forecasting (Week 3)

### 6.1 Target and features

**Target:** net LP return over the following week, per pool.

**Features — all strictly known at time t:**

```
realized_vol_7d, realized_vol_30d
implied_vol (Deribit DVOL as proxy)
fee_tier
volume_tvl_ratio_7d
liquidity_concentration (Herfindahl over ticks)
mev_intensity_30d
gas_price_median_7d
pool_age_days
tvl_usd
vol_of_vol
```

**No lookahead. Write a test asserting it.**

### 6.2 Validation

**Purged, embargoed cross-validation.** Weekly overlapping targets otherwise produce a fake R². Purge = target horizon; embargo ≥ 1 week.

Model: LightGBM. Baseline: predict the historical mean. If LightGBM doesn't beat the mean out of sample, say so.

### 6.3 H6 — theory vs ML ⭐

|  | Method |
| --- | --- |
| **Analytical** | σ²/8 with a HAR-RV volatility forecast |
| **ML** | LightGBM on the feature set |

Out-of-sample RMSE and directional accuracy.

**If the closed form wins, that is the better result** and deserves prominence. Theory beating a black box is rarer and signals understanding rather than fashion.

### 6.4 Acceptance criteria

- [ ] No-lookahead test passes
- [ ] Purged CV implemented and documented
- [ ] Both models evaluated on identical out-of-sample folds
- [ ] Feature importances reported and economically sensible

---

## Stage 7 — Strategy (Week 4)

### 7.1 Specification

```
Weekly rebalance.
For each pool: predicted_net > threshold → allocate.
Weights ∝ predicted net, or equal-weight among qualifying pools.
Costs: gas for entry/exit/re-centre, swap fees to rebalance, hedge funding.
```

**Benchmarks:**

- Equal-weight LP across all pools
- Hold the underlying tokens
- 50/50 rebalanced portfolio
- Best single pool ex-post (the unbeatable benchmark — include it for honesty)

### 7.2 Reporting

**Deflated Sharpe Ratio**, with the count of specifications tried. Log every configuration in `outputs/specification_log.csv` as you go, not retrospectively.

Capacity estimate: at what position size does approach B (Stage 2.2) break, and at what size does the LP position itself move the pool?

### 7.3 Acceptance criteria

- [ ] Full costs from the first run
- [ ] Deflated Sharpe reported alongside raw
- [ ] Capacity stated
- [ ] Result reported honestly if negative — "advertised LP yields are systematically overstated and the strategy does not recover them" is a legitimate paper

---

## Stage 8 — Original mathematics (Week 4, appendix)

### Optimal range width

Narrow range → more fees per dollar, more LVR per dollar, higher probability of exiting range.

Set up: expected net return as a function of half-width `w`, under a GBM price process with volatility σ, fee tier f, and a re-centring cost.

```
maximise:  E[fees(w)] − E[LVR(w)] − E[recentring_cost(w)]
```

**Open question:** is there a closed form, or does it require numerical solution? Either answer is publishable; a closed form is better.

Validate the theoretical optimum against the empirical optimum from the data.

---

## Repository structure

```
lvr-mev/
├── README.md
├── DECISIONS.md              ← Stage 0 choices + reasoning for every open question
├── config.yaml
├── dune/                     ← published SQL, part of the contribution
├── data/{raw,interim,processed}/
├── src/
│   ├── fetch/       rpc_client.py, binance_data.py, subgraph.py, flashbots.py, gas.py
│   ├── build/       pool_state.py, align.py, position.py, fees.py, lvr.py, mev.py,
│   │                hedge.py, decomposition.py
│   ├── model/       volatility.py, features.py, forecast.py, purged_cv.py
│   ├── strategy/    allocate.py, backtest.py
│   ├── theory/      range_width.py, fee_tier.py
│   └── utils/       precision.py, config.py, speclog.py, stats.py, plotting.py
├── notebooks/
├── outputs/{figures,tables}/
└── tests/
```

`precision.py` exists because sqrtPriceX96 arithmetic must never touch float64. Centralise it.

---

## Precision requirements — consolidated

| Item | Requirement | Failure mode |
| --- | --- | --- |
| sqrtPriceX96 | Integer/Decimal only until final division | Silent price error ~1e-8 relative, compounds in LVR |
| Token decimals | USDC 6, WETH 18, WBTC 8 — verify per pool | Price off by 10^12 |
| token0/token1 | Address-sorted, verify per pool | Price inverted |
| Signed ABI fields | Decode at 256 bits, range-check after | int24 tick decodes to a 78-digit number |
| Big-int persistence | Store as strings, load to `object` dtype | int64 overflow above 9.22 WETH |
| Tick ↔ price | `P = 1.0001^tick`, round-trip exact | Range boundaries wrong |
| CEX alignment | Last observation closing at or before the block timestamp | Lookahead bias |
| Gas | Actual historical price at the block | Cost understated in high-gas periods |
| Fee accrual | Only while in range | Overstates returns |
| Annualisation | State the convention explicitly, once, in config | Incomparable tables |

---

## Where to explore rather than follow

These are unsettled and worth real investigation. Record conclusions in `DECISIONS.md`.

1. **MEV attribution to LPs** (4.2) — the literature is thin and the right answer is not obvious
2. **Volatility estimator for analytical LVR** (3.2) — which one best matches empirical LVR is an empirical question
3. **Block timestamp alignment** (1.3) — does the rule materially change LVR?
4. **Approach B capacity limit** (2.2) — at what size does the small-position approximation break?
5. **Optimal fee tier as a function of σ** (5.2) — possible clean theoretical result
6. **Optimal range width closed form** (Stage 8)
7. **Hedge rebalance frequency** (0.1) — how large is the hedging error on a path-dependent v3 delta?

If a better approach than the one specified is found at any point, take it — and write down why.

---

## Failure modes to watch

| Symptom | Likely cause |
| --- | --- |
| LVR ~0 | Price alignment broken, or comparing pool price to itself |
| LVR enormous (>100% annualised) | Decimals wrong, or double-counting blocks |
| Fees far above reference | Accruing while out of range |
| Model R² > 0.5 out of sample | Lookahead. Find it |
| Net return positive everywhere | LVR not actually subtracted, or sign error |
| Everything matches on day 1 and breaks at scale | Precision loss from float64 |

---

## Stage gates — do not pass on failure

| Gate | Criterion | State |
| --- | --- | --- |
| **After Stage 1** | Price reconstruction validated against an independent reference | **PASSED** |
| **After Stage 2** | Fee accrual within 2% of reference | pending |
| **After Stage 3** | LVR positive, correct order of magnitude, scales with vol | pending |
| **After Stage 6** | No-lookahead test passes | alignment half passing |

A failed gate means stop and diagnose, not proceed and hope.
