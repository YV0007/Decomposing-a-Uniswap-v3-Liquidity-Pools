# DECISIONS

Every choice that propagates into a table, with its reasoning. Stage 0 decisions
are settled here **before** Stage 1 code. Open questions are recorded here with
status `OPEN` and closed here with evidence.

Format for every entry: **what was decided**, **why**, **what would reverse it**.

---

## Stage 0 — settled before any code

### 0.1 Delta-neutral or raw? — **DECIDED: delta-hedged primary, raw as robustness**

**Decision.** The headline decomposition is delta-hedged. Raw LP is reported
alongside, in every table, as a robustness column — never as the lead number.

**Why.** The paper is about market-making economics: fees earned against adverse
selection. Raw LP return is dominated by whether ETH went up over the sample,
which is a directional bet with a variance an order of magnitude larger than the
quantity being measured. Reporting raw as the headline would mean the sign of
the paper's central finding is set by the ETH price path.

**Hedge specification, fixed now:**

| Parameter | Baseline | Alternatives swept |
|---|---|---|
| Instrument | Binance ETH perpetual | Deribit ETH perpetual |
| Rebalance frequency | Daily | Hourly, weekly |
| Funding cost | Actual realised funding | — (no assumed-zero variant in headline) |
| Hedge ratio | LP position delta from the v3 position formula | **Not** 0.5 |

**What would reverse it.** If the hedging error on a path-dependent v3 delta
(open question 7) turns out to swamp the LVR being measured, the delta-hedged
number stops being cleaner than the raw one and the lead flips. Measure before
concluding.

### 0.2 Position specification — **DECIDED**

| Parameter | Baseline | Swept later |
|---|---|---|
| Notional | $100,000 | 10k / 100k / 1m / 10m (also the capacity study) |
| Range half-width | ±10% around entry | ±2 / 5 / 10 / 25 / 50% |
| Re-centring rule | On exit from range | Never, weekly |
| Entry timing | Monthly cohorts (first of month) | Rolling |

**Why.** $100k is small enough that the position does not move the pool and the
approach-B fee approximation (Stage 2.2) holds, and large enough that gas is a
real but not dominant cost — which is the regime an actual LP faces. ±10% is
wide enough to stay in range through ordinary weeks and narrow enough that
concentration matters. Monthly cohorts give independent entry points without
manufacturing overlapping observations.

**What would reverse it.** Nothing about the baseline is load-bearing — all four
are config parameters and all four get swept. The commitment is that the
*headline* table uses these values, chosen before results were seen.

### 0.3 Universe — **DECIDED**

Core: ETH/USDC at 5bp, 30bp, 100bp. Nothing else until the core passes the
Stage 1, 2 and 3 gates end to end for one pool, one month.

**Why.** H4 is a natural experiment and needs exactly these three: same asset,
same volatility, different fee. Breadth adds pools, not evidence.

**What would reverse it.** Nothing. Scope creep to more pools or to L2 is the
first thing cut, per the risk register.

### 0.4 Data source substitution: Dune -> Ethereum archive RPC — **DECIDED**

**Decision.** On-chain event data comes from `eth_getLogs` against public
Ethereum archive RPC endpoints, not from Dune Analytics. Dune remains a
cross-check for MEV classification (Stage 4.1) where its pre-classified tables
are genuinely additive.

**Why.** Three reasons, in order of weight.

1. **Precision.** Raw logs deliver every field as a canonical hex integer.
   `sqrtPriceX96` is a uint160 and `liquidity` a uint128 — both exceed int64,
   and a SQL warehouse's numeric handling plus a CSV/parquet round trip is
   exactly where a silent float coercion enters. Decoding the log ourselves
   means the integer is never handled by anything that could round it.
2. **Ordering.** `logIndex` is the exact within-block ordering that sandwich
   classification depends on, delivered natively rather than as a column that
   might be dropped or re-sorted.
3. **Access.** Dune's API requires a key; the free archive endpoints do not.
   This keeps the stated total data cost of EUR 0 real rather than nominal.

A fourth benefit, unplanned: the same query can be replayed against several
independent providers, and agreement between them is a cross-check no single
warehouse can offer.

**Endpoints**, in preference order: `gateway.tenderly.co/public/mainnet`
(serves 50k-block spans), `docs-demo.quiknode.pro`, `rpc.mevblocker.io`.

**Cost.** The `dune/*.sql` files are still written and published — the
transparency contribution was the queries being public, and they remain the
readable statement of what is being extracted, executable by anyone with a
free Dune account.

**What would reverse it.** If public archive endpoints rate-limit below what a
full three-year, multi-pool pull needs, Dune with a free key becomes the
pragmatic source and this entry is revised. Measured so far: 50k blocks in
~3.3s, i.e. a month in ~5 requests.

### 0.5 Pool verification — **DONE 2026-09-05**

All five configured pools verified directly against the chain rather than
against a block explorer's rendering: `token0()`, `token1()`, `fee()`,
`tickSpacing()` from the pool contract and `decimals()` from both ERC-20s.
34 of 34 checks pass. `scripts/verify_pools.py` is the gate and re-runs on
demand.

One note on the check itself: the inversion rule is "invert the raw price
exactly when token0 is the stable and token1 is the risky asset". For
USDC/USDT both legs are stable, the price is ~1 either way, and the orientation
is a free choice — so the check abstains there rather than asserting a
convention it cannot justify.

---

## Open questions — investigate, do not follow

Each stays `OPEN` until closed here with evidence. Closing one means: what was
tested, what the numbers were, what was chosen, and what would reverse it.

| # | Question | Stage | Status | Owner file |
|---|---|---|---|---|
| 1 | Correct way to attribute MEV cost to LPs | 4.2 | OPEN | `src/build/mev.py` |
| 2 | Which volatility estimator best matches empirical LVR | 3.2 | OPEN | `src/model/volatility.py` |
| 3 | Does block-timestamp alignment materially change LVR | 1.3 | OPEN | `src/build/align.py` |
| 4 | At what position size does approach B break down | 2.2 | OPEN | `src/build/fees.py` |
| 5 | Optimal fee tier as a function of sigma | 5.2 | OPEN | `src/theory/fee_tier.py` |
| 6 | Optimal range width — closed form or numerical | 8 | OPEN | `src/theory/range_width.py` |
| 7 | Hedging error on a path-dependent v3 delta | 0.1 | OPEN | `src/build/hedge.py` |

### Q1 — MEV attribution to LPs — OPEN

The distinction that has to be got right: **sandwiching primarily harms the
trader, not the LP.** The LP earns fees on all three legs of a sandwich. The LP
effect is indirect — sandwich flow is informed flow, and it degrades the quality
of the order flow the LP faces.

Candidate answers:

- **(a) Exclude sandwich volume from "good" fee revenue.** Treats sandwich fees
  as not-really-earned. Defensible if sandwich volume would not exist absent the
  victim, i.e. it is not incremental uninformed flow.
- **(b) Treat it as neutral.** Fees are earned on it; the LP is indifferent to
  who trades. Defensible under a pure fee-accounting view.
- **(c) Measure the toxicity of the resulting flow.** Attribute a cost equal to
  the adverse selection the sandwich flow imposes, separately from the fees it
  pays. Closest to how a dealer would account for it, and closest to the
  companion GEX paper's framing.

**Working preference: (c), with (a) and (b) reported as bounds.** Not yet
closed — the literature is thin and the choice needs to be argued, not asserted.
Config currently sets `mev.attribution_method: flow_toxicity` as a placeholder
so the pipeline runs; the value is provisional until this entry is closed.

### Q2 — Volatility estimator for analytical LVR — OPEN

Baseline is realized variance from 5-minute log returns over a trailing 24h.
Microstructure noise argues against 1-minute; jumps argue for bipower variation,
since the sigma^2/8 result is derived under a diffusion and jumps are not
arbitraged the same way. Test all four against empirical LVR; the one that
matches best is itself a small finding.

### Q3 — Block timestamp alignment — OPEN

Block timestamps are proposer-set and can drift by seconds. Baseline is the last
CEX trade at or before the block timestamp. Alternatives: parent-block
timestamp, mid-block interpolation. If LVR moves materially across these, that
is a robustness slide, not a footnote.

### Q4 — Approach B capacity limit — OPEN

Approach B uses the `liquidity` field on each Swap event as active liquidity.
Valid while the simulated position is small relative to the pool. The size at
which it breaks is the capacity limit of any strategy built on this, so it needs
a number, not a hand-wave.

### Q5 — Optimal fee tier as a function of sigma — OPEN

Higher tiers earn less gross but suffer proportionally less LVR, because
arbitrage only fires when the price gap exceeds the fee. Whether an interior
optimum exists as a function of sigma is a clean theoretical question.

### Q6 — Optimal range width — OPEN

Maximise `E[fees(w)] - E[LVR(w)] - E[recentring_cost(w)]` in the half-width `w`
under GBM. Closed form preferred, numerical acceptable. Validate the theoretical
optimum against the empirical optimum from the sweep in `position.sweeps`.

### Q7 — Hedge rebalance frequency — OPEN

v3 concentrated positions have path-dependent delta that changes as price moves
through the range. Whether daily rebalancing leaves a hedging error large enough
to matter is measurable, so measure it.

---

## Modelling choices that are not open questions

Recorded so they are not silently re-litigated.

- **LVR is not impermanent loss.** IL compares to holding. LVR compares to a
  continuously rebalanced portfolio holding the same instantaneous delta. These
  are routinely conflated; this paper does not.
- **LVR is not the sum of arbitrageur profits.** Arbitrageur profit is LVR minus
  fees paid minus gas. LVR is gross adverse selection; extraction is what
  survives frictions. Both are reported, and the gap between them is part of H3.
- **No forward-looking data at any alignment step.** Enforced by test, not by
  care.
- **Mainnet only.** L2 gas economics and MEV structure differ. Scope stated, not
  hidden.
- **Retrospective universe.** Pools were chosen knowing which survived. The
  survivorship dimension is acknowledged, not corrected for.

---

## Stage 1 — findings and defects

### 1.1 CEX reference granularity: 1s klines, not aggregate trades — **DECIDED**

**Decision.** The reference series is Binance 1-second klines, not aggregate
trades. Aggregate trades are downloaded for individual days to validate the
substitution.

**Why.** A 1s kline's `close` *is* the last trade in that second, so at the
~12s resolution we consume it the two carry the same information — for 59 MB
per month against 195 MB, and 2.7M rows against tens of millions.

**The boundary, which is the part that matters.** The kline for second `s`
covers `[s, s+1)`, so its close may be timestamped *after* `s`. Matching a
block at `T` to the kline for second `T` therefore admits up to one second of
lookahead. The correct match is the latest kline with `s <= T - 1`. One extra
second of known, bounded staleness is much safer than a small invisible peek
forward. Asserted in `tests/test_no_lookahead.py`, not left to care.

### 1.2 DEFECT FOUND AND FIXED — ABI sign extension of int24 ticks

**What happened.** The Swap decoder read the `tick` field at its declared width
of 24 bits. The ABI sign-extends signed integers to the full 32-byte word, so a
tick of -2 arrives as `0xffff...fffe`; read at 24 bits it decodes to a 78-digit
positive number rather than -2.

**Why it hid.** ETH/USDC ticks sit near +205,000, where both readings agree, so
every check up to that point passed. It surfaced only on USDC/USDT, which
trades at a price near 1 — ticks near zero, routinely negative. All 3,306
swaps sampled in one window were affected.

**Why it surfaced at all.** Parquet refused to store the oversized integer. In
memory, or through CSV, it would have passed silently into the price
cross-check. This is precisely the "matches on day 1 and breaks at scale"
failure mode in the risk register, and it arrived on schedule.

**Fix.** Decode every ABI signed integer at 256 bits and range-check against the
declared width afterwards (`_decode_signed_word`). Regression tests cover ticks
from MIN_TICK to MAX_TICK including -1 and -2. Swap caches bumped to v3 —
earlier caches may hold garbage ticks for any pool trading near price 1.

**Standing lesson.** The Stage 1 gate (`check_price_against_tick`) would have
caught this independently, because a garbage tick cannot bracket the price
decoded from `sqrtPriceX96`. Cross-checking two fields the chain emits about
the same quantity is worth more than checking one field against an external
source.

### 1.3 Stablecoin basis is a real confound — **HANDLED**

The pool quotes ETH in USDC; the Binance reference quotes ETH in USDT. Any
USDC/USDT basis enters the measured gap as a bias unrelated to AMM staleness.
Binance published no ETHUSDC or USDCUSDT series for the sample period, so the
basis is measured **on-chain** from the USDC/USDT 1bp pool — the tightest venue
for exactly that pair — and divided out.

Measured for 2023-01: median 0.999851 USDT per USDC, i.e. **-1.49 bp** from
parity. Small, but of the same order as the 5bp pool's entire mean gap, so it
is not ignorable there. Both raw and basis-corrected figures are reported.

### 1.4 First economic result — the no-arbitrage band is visible

Pool-versus-CEX price gap, ETH/USDC, January 2023, basis-corrected:

| Pool | n blocks | mean abs gap | p95 abs gap | fee |
|---|---|---|---|---|
| ETH/USDC 5bp | 135,091 | 4.08 bp | **8.18 bp** | 5 bp |
| ETH/USDC 30bp | 9,959 | 22.99 bp | **33.63 bp** | 30 bp |

Each pool's p95 gap sits at roughly its own fee tier. That is the no-arbitrage
band, measured directly: arbitrage fires only once the gap exceeds fee plus
gas, so the gap random-walks inside a band the fee sets and is pushed back at
the edge.

This is the mechanism H4 rests on, confirmed before anything is built on it,
and it is strong evidence the pipeline measures the real quantity rather than
noise. It also implies the H4 prediction directly: the 30bp pool tolerates ~4x
the price dislocation before an arbitrageur corrects it, so it should suffer
proportionally less LVR per unit of volatility.

**Not yet claimed:** that this converts into higher *net* return. Gross fee
income falls with the tier too, and the 30bp pool traded on 9,959 blocks against
the 5bp pool's 135,092 — a 13.6x difference in trade count on the same asset
over the same month. Which effect dominates is Stage 5's question.

### 1.5 Open question 3 partially answered — alignment barely matters

Alignment sensitivity for ETH/USDC 30bp, January 2023:

| Rule | mean abs gap | p95 abs gap | median staleness |
|---|---|---|---|
| last trade at or before block ts (baseline) | 22.60 bp | 33.64 bp | 1 s |
| one slot earlier | 20.69 bp | 31.19 bp | 13 s |
| midpoint interpolation (lookahead) | 22.75 bp | 36.46 bp | -6 s |

The three rules move the mean absolute gap by under 2 bp on a 22 bp base. The
question earns a sentence and a table, not a slide.

One observation worth keeping: the *staler* rule gives a slightly **smaller**
gap. A reference 13 s old matches the pool better than one 1 s old, which is
consistent with the pool price reflecting a trade submitted a block earlier.
Worth a look when empirical LVR is computed, since it bears on which price the
arbitrageur is actually trading against.

---

## Log of reversals

Anything decided above and later changed goes here with the date and the
evidence that forced it. Empty is fine; silently editing an entry above is not.

| Date | Entry | Was | Now | Evidence |
|---|---|---|---|---|
| — | — | — | — | — |
