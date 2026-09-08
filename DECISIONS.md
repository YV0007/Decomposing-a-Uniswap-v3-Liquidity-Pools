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
| 1 | Correct way to attribute MEV cost to LPs | 4.2 | **CLOSED** (4.2) | `src/build/mev.py` |
| 2 | Which volatility estimator best matches empirical LVR | 3.2 | **CLOSED** | `src/model/volatility.py` |
| 3 | Does block-timestamp alignment materially change LVR | 1.3 | **CLOSED** (1.5) | `src/build/align.py` |
| 4 | At what position size does approach B break down | 2.2 | **CLOSED** (8.4) | `src/theory/range_width.py` |
| 5 | Optimal fee tier as a function of sigma | 5.2 | **CLOSED** — premise was wrong | `src/theory/fee_tier.py` |
| 6 | Optimal range width — closed form or numerical | 8 | **CLOSED** (8.1-8.2) | `src/theory/range_width.py` |
| 7 | Hedging error on a path-dependent v3 delta | 0.1 | **CLOSED** | `src/build/hedge.py` |

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

### Q2 — Volatility estimator — **CLOSED: keep 5-minute RV**

Analytical LVR is linear in variance, so an alternative estimator rescales it
exactly and the horse race is cheap. All four run against 2,697 pool-days.

| Estimator | beta | R² | ratio of totals | \|beta − 1\| |
|---|---|---|---|---|
| Bipower (jump-robust) | **0.840** | 0.594 | 1.085 | **0.160** |
| RV 5-min (baseline) | 0.798 | 0.609 | **1.007** | 0.202 |
| RV 1-min | 0.720 | **0.693** | 0.987 | 0.281 |
| Garman-Klass | 0.604 | 0.466 | 1.268 | 0.396 |

**No estimator wins on every criterion**, which is the honest answer rather than
an inconvenience:

- **Bipower** gets the slope closest to one. Its ratio of 1.085 says empirical
  LVR *exceeds* what the continuous part of variance alone predicts, by 8.5% —
  so jumps do transfer value to arbitrageurs, they are not simply noise.
- **1-minute RV** tracks the variation best (R² 0.693), which is what more
  observations buys, but has the worst slope in the RV family — consistent with
  microstructure noise inflating the variance so that empirical LVR per unit of
  analytical falls.
- **5-minute RV** has the best level match by a wide margin (1.007 against
  1.085 and 1.268) and an R² within 1.4% of the best.
- **Garman-Klass** is worst on everything. Range estimators assume no gaps, and
  a 24h crypto tape resampled to minutes has plenty.

**Decision: keep 5-minute RV as the baseline.** The level match is what the
decomposition depends on — the LVR column is a dollar amount, not a slope — and
5-minute RV is essentially unbiased there while bipower runs 8.5% light and
Garman-Klass 27% heavy. Bipower is reported alongside in the H3 table because
its better slope is the evidence for the jump interpretation.

**What would reverse it.** If the paper's emphasis moved from levels to
sensitivity — forecasting LVR *changes* rather than measuring LVR *amounts* —
bipower's slope advantage would matter more than 5-minute RV's level advantage.

### Q3 — Block timestamp alignment — **CLOSED, then reopened, then re-closed (R.10)**

Block timestamps are proposer-set and can drift by seconds. Baseline is the last
CEX trade at or before the block timestamp. Alternatives: parent-block
timestamp, mid-block interpolation. If LVR moves materially across these, that
is a robustness slide, not a footnote.

### Q4 — Approach B capacity limit — OPEN

Approach B uses the `liquidity` field on each Swap event as active liquidity.
Valid while the simulated position is small relative to the pool. The size at
which it breaks is the capacity limit of any strategy built on this, so it needs
a number, not a hand-wave.

### Q5 — Optimal fee tier — **CLOSED, and the premise was wrong** ⭐

The question assumed higher tiers "suffer proportionally less LVR, because
arbitrage only fires when the price gap exceeds the fee". **They do not.** A fee
band does not reduce gross LVR at all.

**The derivation.** In log price, with `g = log(S/P)` the pool-to-external gap,
the AMM invariant `y'(P) = -P x'(P)` gives `dV/dP = x'(P)(S - P)`, so for a v3
position `dLVR = (L sqrt(P)/2) g dp`. An arbitrageur facing fee `f` trades until
the gap reaches `f`, so integrating along one trade from gap `g`:

    LVR per arbitrage event = (L sqrt(P)/4) (g² − f²)

The gap is a driftless walk reflected at `±f`. Local time at a reflecting
boundary accumulates at `sigma²/(2f)` across both boundaries, and each unit
transfers `(L sqrt(P)/2) f`. So

    LVR rate = (L sqrt(P)/2) · f · sigma²/(2f) = L sqrt(P) sigma² / 4

**The `f` cancels.** A wider band makes arbitrage rarer and each event
proportionally larger, and the two effects offset exactly.

**Confirmed numerically**, and it is not a discretisation artefact — the ratio
of banded to frictionless LVR converges to one at every step size tested:

| Steps per year | fee 0.05% | fee 0.30% | fee 1.00% |
|---|---|---|---|
| 35,040 (15-min) | 1.009 | 1.008 | 1.006 |
| 105,120 (5-min) | 1.002 | 1.000 | 0.984 |
| 525,600 (1-min) | 1.001 | 0.995 | 0.989 |
| 3,153,600 (10-sec) | 1.000 | 0.997 | 0.988 |

**Confirmed empirically**, on 3,842 pool-days across a 20x range of fee tiers.
Regressing normalised empirical LVR on variance:

| Pool | fee | slope | se | R² |
|---|---|---|---|---|
| ETH/USDC 5bp | 5bp | 0.00553 | 0.00060 | 0.620 |
| ETH/USDC 30bp | 30bp | 0.00576 | 0.00073 | 0.624 |
| ETH/USDC 100bp | 100bp | 0.00590 | 0.00108 | 0.462 |

The 100bp-minus-5bp difference is **+0.00037, t = +0.30** — indistinguishable
from zero, and with the *opposite* sign to the prediction.

**Answer to Q5: there is no LVR-based optimal fee tier, because fee tiers do not
change LVR.** The tier choice matters only through fee income — rate times
volume — which turns on the volume elasticity, an empirical quantity rather than
a theorem. `optimal_fee_tier` therefore takes that elasticity as an explicit
parameter and the answer tracks it, which is the honest form of the result.

### Q5.1 What this does to H4

H4's prediction had two clauses. The first — higher tiers earn less gross fee
income — is a volume question and stands. The second — they suffer
proportionally less LVR — is **false**, by derivation and by measurement.

This retrospectively explains a Stage 5 number that should have prompted the
question earlier: empirical LVR was 5.54%, 5.92% and 5.45% for the 5bp, 30bp and
100bp pools in January 2023. Flat across a 20x fee range. The data said it
before the theory did.

Combined with the tick-spacing confound (3.4) and the 100bp pool having no
viable size (5.7), **H4 as written is not supportable.** The defensible
replacement is narrower and better founded: *fee tier does not affect LVR; it
affects only fee income, so the tier ranking is an empirical question about
volume, not a theoretical one about adverse selection.*

### Q6 — Optimal range width — OPEN

Maximise `E[fees(w)] - E[LVR(w)] - E[recentring_cost(w)]` in the half-width `w`
under GBM. Closed form preferred, numerical acceptable. Validate the theoretical
optimum against the empirical optimum from the sweep in `position.sweeps`.

### Q7 — Hedge rebalance frequency — **CLOSED: hourly, not daily**

Measured on ETH/USDC 30bp, January 2023, $100k at +/-10%. A perfect hedge would
leave `LP value change + hedge P&L - funding - trading` equal to `fees - LVR`,
which was near zero that month (fees $495, LVR $495). The residual *is* the
hedging error.

| Rebalance | n | hedge P&L | funding | trading | residual | mean error |
|---|---|---|---|---|---|---|
| Hourly | 743 | -$2,760 | -$58 | $66 | **-$392** | 0.070 ETH ($88) |
| Daily | 31 | -$3,113 | -$67 | $44 | **-$715** | 0.748 ETH ($952) |
| Weekly | 5 | -$7,633 | -$158 | $41 | **-$5,140** | 5.477 ETH ($7,445) |

**The daily hedging error is larger than the entire quantity being measured.**
Market-making return that month was roughly $0-500; the daily residual is -$715.
Hedging daily would mean reporting a market-making return whose error bar
exceeds its own magnitude — the delta-hedged variant would be noisier than the
raw one it was chosen to improve on.

Hourly halves the residual for about $22 more trading cost over the month
(0.77% against 0.52% annualised). That is a cheap trade.

**Decision: baseline moves from daily to hourly.** Daily and weekly stay in the
sweep, and weekly is retained specifically to show what the naive choice costs.

**What would reverse it.** If hourly rebalancing proves impractical at scale
across 44 months x 3 pools, or if the residual is dominated by perp-spot basis
rather than discretisation — the residual is still -$392 at hourly, and where
that comes from has not yet been decomposed.

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

## Stages 2-4 — findings and defects

### 2.1 Fee accrual: a third method, used as the reference — **DECIDED**

The plan specifies two approaches: replay every Mint/Burn to rebuild the tick
liquidity map (A), or use the `liquidity` field on each Swap event (B). There is
a third that is strictly better as a *reference*:

**C — `feeGrowthInside`, read from the pool contract at historical blocks.**
Uniswap accounts fees exactly as `L * delta(feeGrowthInside) / 2**128`, derived
from `feeGrowthGlobal` and the `feeGrowthOutside` stored on the range's boundary
ticks. Four `eth_call`s reproduce the contract's own arithmetic with no replay
and no approximation — and it is what the subgraph derives its figures from, so
validating against it is validating against the source rather than a copy.

Valid only where the boundary ticks are initialised. Checked: all 51 ticks on
the spacing-60 grid around the test range are initialised, because on a major
pool real LPs sit at essentially every tick.

B remains the pipeline's method — `feeGrowthInside` can only be read for a range
that already happened, so forecasts, range-width sweeps and hypothetical
positions all need the replay. C is what proves B is right.

### 2.2 DEFECT FOUND AND FIXED — fees lost at the range boundary

**What happened.** Approach B tested whether the *post-swap* tick was in range.
A swap that carries the price out of the range therefore got zero credit for the
part of its path that was still earning.

**How it was localised.** Comparing over a strictly in-range sub-period gave
+0.27% / -0.43%, against -1.88% over the full month. That located the entire
error in the single boundary-crossing swap on the day the position exited,
rather than in the liquidity estimator — which was the initial suspicion, and
was wrong: sweeping post-swap, pre-swap and mean liquidity moved nothing.

**Fix.** Pro-rate each swap's fee by the fraction of its tick path that lay
inside the range. Max error 1.88% -> 0.52% against a 2% gate.

The pro-rating is linear in tick space, which is an approximation — fees accrue
with the liquidity actually traversed, and that is not uniform. It is a
first-order correction to a first-order method, and the gate is what says
whether it is good enough.

### 2.3 Range-state naming — tick space is not price space

On an inverted pool the tick *falls* as the risky asset appreciates, so a
position whose tick dropped below `tick_lower` has had ETH move *above* the top
of its USD range. The enum is named in tick space, deliberately, because tick
space drives fee accrual and is unambiguous; `price_side()` translates for
anything a human reads. "Below" meaning "ETH rallied" is a trap that would
eventually be read the wrong way round in a caption.

### 3.1 Three LVR measures, not two — **DECIDED**

Splitting the empirical side in two makes H3 sharper, because they answer
different questions:

| Measure | What it is | Depends on the fee tier? |
|---|---|---|
| `lvr_cex_path` | Loss under perfect arbitrage every block | **No — by construction** |
| `lvr_pool_path` | Loss from the pool price actually moving | Yes |
| `lvr_analytical` | `(sigma^2/2) S^2 |dn/dS|` on the position's own amount function | No |

This matters for H4. `cex_path` depends only on the external price path and the
position's shape, so it is *fee-tier-blind*: it cannot show a fee-band effect
even in principle. H4's mechanism lives in `pool_path`. Reporting a single
"empirical LVR" would have made H4 untestable without anyone noticing.

### 3.2 The naive `sigma^2 V / 8` understates a concentrated position

`sigma^2/8` is stated for a *full-range* constant-product pool. Applied to a
concentrated v3 position it understates LVR, because concentration raises price
sensitivity per dollar deployed. The implementation differentiates the
position's own amount function, which handles any range exactly and collapses
back to `sigma^2 V/8` in the full-range limit — asserted in `tests/test_lvr.py`.

**CORRECTION.** An earlier version of this entry reported the amplification as
**1.19x**. That number is real but it is not the concentration effect, and
labelling it so understated the effect by more than an order of magnitude.

1.19x was the ratio of two *whole-period* annualised totals. The concentrated
rate is zero while the position is out of range; the naive textbook rate is not.
Over a month the position spent 73% out of range, two large and opposite errors
very nearly cancelled: ~20x amplification while in range, against a naive
formula charging LVR during a period when a single-sided position cannot lose
any.

Measured like with like — comparing the two rates only on blocks where the
position is actually in range — the amplification is:

| Half-width | measured | `2/delta` closed form |
|---|---|---|
| +/-2% | 83.8x | 101.0 |
| +/-5% | 37.5x | 41.0 |
| +/-10% | **19.6x** | 21.0 |
| +/-25% | 8.3x | 9.0 |
| +/-50% | 4.2x | 4.9 |

The implementation and the closed form `2/delta` (delta = half-width in log
price) are independent, and they agree to within the small-delta approximation
throughout — which validates both.

So a +/-10% position carries roughly **twenty times** the LVR per dollar of a
full-range one. Both quantities are now reported separately:
`in_range_concentration_factor` is the amplification, and the whole-period ratio
is what an analyst gets wrong by applying the textbook form naively.

### 3.4 Tick spacing is bundled with the fee tier — a confound in H4 ⚠️

Uniswap ties tick spacing to the fee tier: 10 ticks at 5bp, 60 at 30bp, 200 at
100bp. Snapping a requested range outward to that grid therefore inflates it by
a different amount on each tier:

| Requested +/-2% | realised | inflation | ticks wide |
|---|---|---|---|
| ETH/USDC 5bp | 2.07% | 1.04x | 41 |
| ETH/USDC 30bp | 2.43% | 1.21x | 8 |
| ETH/USDC 100bp | 3.05% | **1.52x** | 3 |

**The tiers cannot hold the same position.** So H4's "same asset, same
volatility, different fee" is not a clean natural experiment: the tiers differ
in minimum range granularity as well as in fee, and a cross-tier comparison at a
fixed *requested* width is comparing different *realised* positions. Since LVR
per dollar goes as `2/delta`, a 1.5x difference in realised width is a 1.5x
difference in LVR before any fee-band effect is considered.

Mitigations, to be applied in Stage 5: compare at fixed *realised* width rather
than fixed requested width, and report the realised width alongside every row.
At +/-10% the inflation is 1.06x / 1.11x / 1.16x, so the confound is modest at
the baseline and severe only for narrow ranges.

### 3.5 Arithmetic +/-w is not centred in log price

`[S(1-w), S(1+w)]` has geometric mean `S*sqrt(1-w^2)` — 13% below spot at
w = 0.5. The price process and the range-width optimisation are both specified
in log price, so `snap_range(..., log_centred=True)` provides the symmetric
alternative. The baseline stays arithmetic because that is how range widths are
quoted in practice; the log-centred variant is swept in robustness.

### 3.3 `lvr_pool_path` has a validity limit — **GUARDED**

The measure marks a whole pool move at the external price of the *ending*
block. Sound when consecutive trades are seconds apart; meaningless over a
multi-hour gap, because the external price has itself travelled.

Inter-trade gaps, January 2023:

| Pool | median | p99 | max | share of \|LVR\| from gaps > 10 min |
|---|---|---|---|---|
| ETH/USDC 5bp | 12 s | 72 s | 252 s | **0.0%** |
| ETH/USDC 30bp | 48 s | 2,981 s | 22,668 s | **10.6%** |
| ETH/USDC 100bp | 144 s | 60,500 s | 185,328 s | **49.6%** |

`compute_lvr` now reports `pool_path_stale_share` and sets
`pool_path_reliable=False` above 25%. Half the 100bp pool's pool-path LVR rests
on unmarkable intervals, so its -7.55% figure is withheld rather than reported.
Without this guard it would have looked like evidence *against* H4.

### 4.1 DEFECT FOUND AND FIXED — the sandwich classifier was mostly false positives

**What happened.** Same-address, same-block, opposite-direction bracketing — the
rule as specified — fires on any address that trades both ways in one block.
Routers, aggregators and market makers all do.

**How it showed.** Three signals, all from the data:
- 45.3% of detected "sandwiches" were **loss-making**. A sandwich is profitable
  by construction.
- The top 1% of events carried **105%** of total profit; the remainder netted
  negative.
- The largest candidate sold 1,245,885 USDC on the front leg and bought back
  10,000 on the back. The legs did not reverse.

**Fix.** Three constraints, each a swept parameter:
- **Reversal** — the back leg must return within 10% of what the front leg
  acquired. This is the constraint that does the work.
- **Span** — legs within 24 positions. A sandwich brackets its victim.
- **Profit** — positive, by construction.

**Result on ETH/USDC 5bp, January 2023:** 2,620 candidates -> **241**; attacker
profit $1,565,909 -> **$394,217**. The tolerance sweep behaves as a correct
constraint should: the loss-making share falls monotonically 10.0% -> 0.0% as
reversal tightens, and the **median reversal ratio of the surviving set is
exactly 1.0000** — real searchers unwind precisely. The unconstrained number
was inflated roughly 4x.

### 4.2 Q1 MEV attribution — **working preference REVISED to `neutral`**

Walking a sandwich through from the LP's side changes the answer. The attacker
buys and the LP sells; the victim buys at the worse price and the LP sells
*better* than it otherwise would; the attacker sells back and the LP buys back.
The LP has done a round trip, ends near the inventory the victim alone would
have left it, and has earned a fee on all three legs instead of one. **The
victim pays. The LP is not the counterparty being exploited.**

So the flow-toxicity story is weaker than it first looked. It is a *dynamic*
claim — that sandwiching degrades execution and drives uninformed flow away over
time — and that is not identified from one pool's swap log.

**Revised position:** `neutral` leads for the direct decomposition;
`exclude_sandwich_volume` is the conservative bound; sandwich intensity is
carried as a forecasting covariate (`mev_intensity_30d`) rather than dressed up
as a per-block cost. Config updated from `flow_toxicity`.

This supersedes the working preference recorded under Q1 above.

### 4.3 Bundle-level identification is unavailable — **SCOPE LIMITATION**

The Flashbots public relay serves only recent slots and returns empty for 2023.
So address rotation between the front and back legs cannot be caught, and the
same-address count is a **one-sided** bound: it undercounts, and by an unknown
amount. A Dune key would partly recover this. Stated in the limitations.

### 5.1 In-range share must be time-weighted

Reported as a share of *traded blocks*, the same position on the same price path
showed 23.2% / 14.8% / 11.9% across the 5bp, 30bp and 100bp pools — an artefact
of trade frequency, since the 5bp pool trades ~350x more often. Time-weighted it
is 27.1% / 27.2% / 27.9%, which is what it must be. Any cross-sectional
statistic over pools with different trade frequencies needs the same treatment.

### 5.2 First decomposition — ETH/USDC, January 2023

$100k at +/-10%, never re-centred, raw (unhedged) variant. Annualised.

| Pool | in range | fees | LVR (cex path) | LVR (analytical) | gas | net |
|---|---|---|---|---|---|---|
| ETH/USDC 5bp | 27.1% | +6.47% | -5.54% | -4.47% | -0.26% | **+0.67%** |
| ETH/USDC 30bp | 27.2% | +5.71% | -5.92% | -4.51% | -0.34% | **-0.55%** |
| ETH/USDC 100bp | 27.9% | +6.80% | -5.45% | -4.12% | -0.43% | **+0.92%** |

MEV excluded (neutral attribution, per 4.2), so these are the full picture on
the direct-P&L view.

**What can be said:** all three tiers sit within a percentage point of zero net
return. Fee income and LVR very nearly cancel, which is what an efficient market
in liquidity provision would look like.

**What cannot be said yet:** anything about H4's ranking. One month, one entry
date, one range width, no confidence intervals — and January 2023 was a strong
uptrend, which is the regime least favourable to a fee band, since the price
trends straight through it rather than oscillating inside it. The fee tier's
protection plausibly depends on the price path's mean reversion, not just its
volatility. That is a hypothesis the full sample can test and this month cannot.

### 5.3 Advertised APR computed on-chain, not from the subgraph

The Graph's gateway now needs a key and everything required is readable from the
chain: TVL from `balanceOf` at historical blocks, pool fee revenue from swap
amounts. `src/fetch/pool_metrics.py` replaces the planned subgraph fetcher.

Convention: **pool fee revenue over the window / TVL, annualised** — the common
dashboard form. Two properties of it are worth stating, because they are exactly
why it overstates what an LP earns. It divides by *total* TVL as though every
dollar earned every fee, when in v3 only liquidity spanning the current tick
earns anything. And it is gross of LVR, MEV and gas.

TVL is averaged across the endpoints rather than taken at one. On a month where
ETH moved 40%, an endpoint TVL would swing the advertised figure by tens of
percent purely through the choice of date.

Measured, January 2023: **40.41%** (5bp), **15.48%** (30bp), **12.28%** (100bp).

### 5.4 The gap is mostly NOT LVR — the thesis needs qualifying ⚠️

Setting the advertised APR beside the realised net return gives a headline gap
that looks devastating: 40.41% advertised against +0.67% realised on the 5bp
pool. Attributing that gap to adverse selection would be wrong, and easy to
catch. It has three distinct causes carrying different messages.

| Pool | advertised | range mgmt | concentration | gross fees | LVR | gas | **net** |
|---|---|---|---|---|---|---|---|
| 5bp | +40.41% | -29.46% | -4.47% | +6.47% | -5.54% | -0.26% | **+0.67%** |
| 30bp | +15.48% | -11.27% | +1.50% | +5.71% | -5.92% | -0.34% | **-0.55%** |
| 100bp | +12.28% | -8.85% | +3.37% | +6.80% | -5.45% | -0.43% | **+0.92%** |

Share of the advertised-to-net gap:

| Pool | range management | LVR + MEV + gas |
|---|---|---|
| 5bp | **74%** | 15% |
| 30bp | **70%** | 39% |
| 100bp | **78%** | 52% |

**Range management dominates.** The advertised figure implicitly assumes capital
earns all the time; a +/-10% position that is never re-centred sits out of range
73% of the month and earns nothing there. That is a cost of *using a
concentrated range*, not adverse selection, and an LP could reduce it by
re-centring or going full-range — at the cost of gas or of lower fee capture.

**The concentration effect has an unexpected sign on the busiest pool.** On the
5bp pool a +/-10% position captures **less** than a proportional share of fees
(-4.47%): the pool's own LPs cluster far tighter than +/-10%, so this position is
*wider* than average and earns below the per-dollar rate the advertised figure
implies. On the thinner 30bp and 100bp pools the same range is tighter than
average and the sign flips positive.

**What this means for the paper.** The thesis — that advertised yields are gross
of costs LPs actually pay — survives, but the honest version is narrower than
the headline number suggests. LVR is the *irreducible* part: an LP can avoid
range-management cost by choosing a different strategy, and cannot avoid LVR at
all. The right comparison is therefore the advertised APR against a
*well-managed* position, with LVR as the part that remains however the position
is managed. Saying "advertised 40% is really 0.7% because of LVR" would
overstate our own result by roughly five times.

This also reframes H4 and Stage 8: if range management is the dominant cost,
then the optimal-range-width derivation moves from an appendix curiosity to
something close to the main event.

---

## Stage 8 — optimal range width ⭐

Promoted from appendix by 5.4: if range management is 70-78% of the gap between
advertised and realised return, then how to choose a range is close to the main
question.

### 8.1 The model and its closed form

In log price with driftless Brownian motion, a band of half-width `delta`
re-centred on exit. Three rates, per unit value per year:

| Term | Form | Source |
|---|---|---|
| Fees | `F / delta` | `L = V/(sqrt(P) delta)`, income proportional to `L` |
| LVR | `sigma^2 / (4 delta)` | `l = (sigma^2/2) S^2 |dn/dS|` on the v3 amount function |
| Re-centring | `(g/V) sigma^2 / delta^2` | exit rate `sigma^2/delta^2` from `E[tau] = delta^2/sigma^2` |

    net(delta) = kappa/delta - A sigma^2/delta^2,   kappa = F - sigma^2/4,  A = g/V
    delta* = 2 A sigma^2 / kappa        net* = kappa^2 / (4 A sigma^2)

Second derivative at `delta*` is `-kappa/delta*^3 < 0`. The closed form agrees
with a grid search over the same objective to **0.02%**.

### 8.2 The result that matters: concentration is sign-neutral ⭐

Fees and LVR **both scale as `1/delta`**. Narrowing a range amplifies income and
adverse selection identically, so range width sets the *scale* of the outcome
and never its *sign*. Whether liquidity provision pays is decided entirely by

    kappa > 0   <=>   F > sigma^2 / 4

and not at all by how the LP concentrates.

**Confirmed empirically.** Sweeping nine widths on ETH/USDC 30bp, January 2023,
with re-centring on exit:

| requested | delta | re-centres | fees | LVR | gas | net | fees/LVR |
|---|---|---|---|---|---|---|---|
| +/-1% | 0.0126 | 85 | +460.95% | -498.34% | -22.70% | **-60.10%** | 0.925 |
| +/-2% | 0.0236 | 34 | +258.67% | -283.76% | -9.24% | **-34.33%** | 0.912 |
| +/-5% | 0.0537 | 9 | +118.01% | -127.62% | -2.64% | **-12.25%** | 0.925 |
| +/-10% | 0.1035 | 3 | +62.98% | -68.78% | -1.06% | **-6.86%** | 0.916 |
| +/-25% | 0.2580 | 1 | +27.06% | -29.48% | -0.53% | **-2.95%** | 0.918 |
| +/-40% | 0.4260 | 0 | +18.77% | -20.36% | -0.26% | **-1.85%** | 0.922 |

Across a **34x span of widths** the fee/LVR ratio moves from 0.912 to 0.928 — a
spread of **1.85%**. Fees and LVR scale together, exactly as derived.

`fees * delta` and `lvr * delta` are each near-constant (0.058 -> 0.080 and
0.063 -> 0.087), drifting up slightly at wide ranges where the small-`delta`
approximation weakens — which is the expected direction and magnitude.

### 8.3 January 2023 was a losing month at every width

Fees covered **92%** of LVR. So `kappa < 0`, and the closed form predicts no
interior optimum: losses shrink monotonically as the range widens, and the
least-bad position is the widest. The sweep does exactly that, improving
monotonically from -60.1% to -1.85%.

This reframes the earlier never-re-centred result. That position looked *better*
(-0.55% at +/-10%) only because it spent 73% of the month out of range, where it
earned nothing and lost nothing. Re-centring keeps it exposed to a
negative-margin activity, so staying in range makes the loss larger. **Being out
of range was accidental risk management, not a cost.**

Stated carefully: one month, one pool, one entry date. The full sample will say
whether `kappa < 0` is typical or particular to a 40% trending month.

### 8.4 Open question 4 answered — the tick grid binds, not capacity

Two floors constrain how narrow a range can be, and which binds is a question
about position size.

| Floor | Value on ETH/USDC 30bp | Meaning |
|---|---|---|
| Fee saturation `beta` | 2.95e-4 (2.95 bp) | position dilutes its own fee share |
| Tick grid (60 ticks) | 6.0e-3 (0.602%) | pool cannot express a narrower range |

The grid binds **twenty times** before saturation does. A $100k position holds
0.29% of active liquidity at +/-10%; capacity does not bind until roughly
**$2m** on this pool. Below that the linear fee model is sound; above it the
saturating form `(R/V) beta/(delta + beta)` is required.

This also caught a real modelling error. Without the saturation term the model
diverges: `kappa/delta` grows without bound as the range narrows, and a
calibrated run returned an "optimum" of +/-0.2% paying **364% a year**. That is
the model failing, not a finding, and the bound is what makes it physical.

---

## Stage 5 — full sample ⭐

43 monthly cohorts per pool, 2023-01 to 2026-07. $100k at +/-10%, re-centred on
range exit, hourly hedge. Annualised, averaged across cohorts, with block
bootstrap confidence intervals.

### 5.5 Headline result *(labels corrected — see R.7)*

| Pool | fees | LVR | gas | **market-making** | 95% CI | rebalanced | total (unhedged) | 95% CI | months > 0 |
|---|---|---|---|---|---|---|---|---|---|
| ETH/USDC 5bp | +88.84% | −96.77% | −1.17% | **−9.10%** | [−15.6%, −3.3%] | +0.75% | −8.35% | [−46.3%, +30.0%] | 26% |
| ETH/USDC 30bp | +96.72% | −97.90% | −1.14% | **−2.31%** | [−5.2%, +1.3%] | +2.02% | −0.29% | [−36.6%, +32.6%] | 21% |
| ETH/USDC 100bp | — | — | — | *withheld* | — | — | *withheld* | — | — |

Implemented-hedge returns (market-making less real perp funding and trading) are
−14.06% and −6.34%.

**The Stage 0 decision is vindicated by the confidence intervals.** The
market-making interval is far tighter than the unhedged one: **6.2x on the 5bp
pool** (12.3pp against 76.3pp) and **10.6x on the 30bp pool** (6.5pp against
69.2pp). Leading with the unhedged number would have meant reporting a quantity
whose error bar is six to ten times the signal inside it.

**And it sharpens the paper's message.** On the 30bp pool the unhedged return is
−0.29% — essentially break-even — but only because a +2.02% directional gain
almost exactly offset a −2.31% market-making loss. *LPs who made money made it
from holding ETH, not from providing liquidity.* That is the claim the
decomposition exists to make, and it is invisible without separating the two.

**A re-centred +/-10% position on ETH/USDC lost money over the sample.** On the
5bp pool the loss is statistically significant both raw and hedged. On the 30bp
pool the raw interval spans zero, but the hedged one does not — stripping the
directional beta is what makes the loss visible, which is exactly why the
delta-hedged variant was chosen as the headline in Stage 0.

Only a fifth to a quarter of months were profitable. The distribution is wide
and left-skewed: the 5bp pool's worst month was -79.8% annualised and its best
+29.4%.

The fee/LVR ratio is **0.918** (5bp) and **0.988** (30bp) — both slightly below
one, and consistent with the Stage 8 finding that these two quantities move
together. LPs are earning very nearly, but not quite, enough to cover adverse
selection.

### 5.6 DEFECT FOUND AND FIXED — the position's own liquidity dilutes its fee share

Approach B computed the position's fee share as `L / L_active`. That is right for
an *infinitesimal* position matched against `feeGrowthGlobal`, and it is what the
Stage 2 gate must use. It is wrong for an LP who actually **deposits**, because
their liquidity joins the denominator: the realised share is
`L / (L_active + L)`.

The gap is the position's own liquidity share, so it is invisible where the
position is small and decisive where it is not:

| Pool | $100k as a share of active liquidity | effect on fees |
|---|---|---|
| ETH/USDC 5bp | 0.20% | negligible |
| ETH/USDC 30bp | 0.46% | negligible |
| ETH/USDC 100bp | **113%** | halves them |

`accrue_fees_approach_b` now takes `deposited` (default `True`, the realistic
case) and the gate passes `deposited=False` so it keeps comparing like with
like.

Correcting it moved the 100bp pool's headline from **+34.65% to -43.10%**, which
is what prompted the capacity check below. Both figures are artefacts.

### 5.7 The 100bp pool has no viable size — **result withheld** ⚠️

A $100k position holds a median 113% of that pool's active liquidity — more than
the entire pool. It is not a price-taker, so the fee model does not apply and the
position would move the price it is being measured against.

Sweeping notional down:

| Notional | share of active liquidity | net | price-taker? |
|---|---|---|---|
| $1,000 | 1.13% | **-94.84%** | yes |
| $2,000 | 2.26% | -50.84% | no |
| $5,000 | 5.66% | -26.25% | no |
| $10,000 | 11.32% | -20.72% | no |
| $25,000 | 28.30% | -23.73% | no |
| $100,000 | 113.19% | -43.10% | no |

**There is no size that works.** Small enough to be a price-taker and gas
destroys it — $22.39 per re-centre is 2.2% of a $1,000 position. Large enough
for gas to be negligible and the position *is* the pool. The viable window is
empty.

That is a finding rather than a failure, and it explains the pool's thinness:
655 swaps a month is what an economically unviable fee tier looks like from the
outside. It is reported as a capacity result, and the 100bp row is withheld from
the decomposition table rather than filled with a number that means nothing.

**Consequence for H4.** The three-way fee-tier experiment is really a two-way
one. Combined with the tick-spacing confound in 3.4, the "same asset, same
volatility, different fee" design is weaker than the plan assumed, and the
comparison that survives is 5bp against 30bp.

### 5.8 What is not yet claimed

One position specification. Range width, re-centring rule and hedge frequency
are all fixed at their baselines, and the sweeps have not been run across the
full sample. The result says that *this* strategy lost money, not that liquidity
provision cannot be profitable — Stage 8 already shows range width cannot change
the sign, but re-centring policy and entry timing have not been swept.

---

## H3 — does sigma^2/8 hold? ⭐

Daily LVR series, 2023-01 to 2026-07, 3,842 pool-days. Empirical LVR regressed
on analytical, Newey-West standard errors (8 lags pooled).

### H3.1 Result

| Sample | n days | beta | 95% CI | alpha | R² | H0: beta=1 | ratio of totals |
|---|---|---|---|---|---|---|---|
| **Pooled (5bp+30bp)** | 2,613 | **0.810** (se 0.070) | [0.672, 0.948] | +48.6 (t 2.8) | **0.618** | **rejected**, p=0.007 | **0.991** |
| ETH/USDC 30bp | 1,306 | 0.838 (se 0.110) | [0.622, 1.054] | +45.5 (t 1.7) | 0.620 | not rejected, p=0.14 | 1.011 |
| ETH/USDC 5bp | 1,307 | 0.784 (se 0.089) | [0.610, 0.958] | +51.2 (t 2.3) | 0.618 | rejected, p=0.015 | 0.972 |
| ETH/USDC 100bp *(excluded)* | 1,214 | 1.012 (se 0.184) | [0.652, 1.372] | +63.5 | 0.504 | not rejected, p=0.95 | 1.335 |

**The closed form explains 62% of daily LVR variation with no fitted
parameters.** For a one-parameter result derived under frictionless continuous
arbitrage, tested against real blocks, gas and fee tiers, that is a strong
showing.

### H3.2 The interesting part is *how* it fails

Two facts that look contradictory and are not:

- **The levels match almost exactly.** Ratio of totals 0.991 pooled. Over three
  and a half years the theory predicted the aggregate transfer to arbitrageurs
  to within 1%.
- **The slope is significantly below one.** beta = 0.810, CI [0.672, 0.948],
  with a positive intercept.

Together these say the theory has the right *average level* but is **too
sensitive to volatility**. It over-responds: predicting more LVR variation than
actually occurs. The residual breakdown shows exactly that, monotonically:

| Volatility quartile | empirical / analytical |
|---|---|
| Q1 (calmest) | **1.186** |
| Q2 | 1.072 |
| Q3 | 1.057 |
| Q4 (most volatile) | **0.923** |

In calm markets LPs lose *more* than the theory says; in volatile ones, *less*.

Both directions have the same explanation, and it is the frictions the
derivation assumes away. `sigma^2/8` assumes arbitrage is continuous and
costless, so the pool is corrected the instant it drifts. In reality arbitrage
fires only when the gap clears fee plus gas.

- **High volatility** — gaps open faster than arbitrageurs close them, and part
  of every large move is never captured. Realised extraction falls short of the
  frictionless bound.
- **Low volatility** — a floor of adverse selection the diffusion misses:
  discrete blocks, jumps at the open, and MEV-ordered flow all transfer value
  even when realised variance is near zero. Hence alpha > 0.

**This is the paper's theoretical contribution, and the gap is the finding.** A
result of "beta = 1, nothing to see" would have been weaker: the deviation is
economically interpretable and it points at exactly the frictions the
decomposition measures separately.

### H3.3 The fee tier that is most arbitraged deviates most

The 5bp pool rejects beta = 1 (p=0.015) and the 30bp pool does not (p=0.14).
Consistent with the mechanism: a tighter fee band means arbitrage fires more
often and the pool tracks the external price more closely, so the *residual*
friction is a larger share of what remains. Suggestive rather than established
— two pools is not a cross-section.

---

## Stage 6 — H5 and H6

Weekly panel, 366 pool-weeks across the 5bp and 30bp pools, 2023-01 to 2026-07.
Purged 5-fold CV, purge 7 days, embargo 7 days, verified leak-free. Every model
scored on the same 352 observations.

### H5 — net LP return is NOT forecastable ❌

| Model | RMSE | OOS R² | directional |
|---|---|---|---|
| mean baseline | 0.00531 | -0.003 | 0.500 |
| LightGBM | 0.00563 | **-0.128** | 0.489 |

Diebold-Mariano favours the **baseline**, p = 0.024. LightGBM is significantly
*worse* than predicting the historical mean.

This is a clean negative result and it is reported as one. Twelve features and
366 pool-weeks against a target with a standard deviation of 0.77% per week:
there is not enough signal, and a gradient-boosted model on a sample that small
finds structure that does not survive the fold boundary. The feature importances
are economically sensible — vol-of-vol, position value, trade count lead — which
is exactly the trap: plausible importances on a model with negative
out-of-sample R² mean nothing.

### H6 — the closed form beats gradient boosting ⭐⭐

| Model | RMSE | OOS R² | directional accuracy |
|---|---|---|---|
| **σ²/8 + HAR-RV** | **1,347.90** | **+0.126** | **0.742** |
| mean baseline | 1,510.49 | -0.097 | 0.500 |
| LightGBM | 1,610.67 | -0.247 | 0.565 |
| σ²/8 + persistence | 1,668.10 | -0.338 | 0.724 |

**Diebold-Mariano, theory against LightGBM: p < 0.0001.** Not a tie — a
decisive win.

The analytical arm is the **only model with positive out-of-sample R²**. It is
11% better than the mean baseline on RMSE and 19% better than LightGBM, and it
calls direction correctly 74% of the time against the black box's 57%.

It also has **one parameter, fixed by derivation**. LightGBM has hundreds fitted
on 366 observations. That asymmetry is the explanation, not an accident: on a
sample this small the model that cannot overfit wins, and the reason it cannot
overfit is that its structure came from economics rather than from the data.

**The volatility model earns its place.** σ²/8 with a HAR-RV forecast (1,348)
beats σ²/8 with persistence (1,668) by 19%. Predicting variance is doing real
work, not decorating the closed form.

**A nuance worth keeping.** The persistence arm has 72% directional accuracy but
the *worst* RMSE. It knows when LVR will be high or low and gets the level
wrong. Direction and magnitude are separable here, and a strategy that only
needs the sign could use a model that a RMSE table would reject.

### H6.1 Why this does not contradict H3

H3 found R² = 0.62; H6 finds 0.13. The difference is measurement versus
forecasting. H3 regressed *contemporaneous* empirical LVR on *contemporaneous*
analytical LVR — given the volatility that actually occurred, the closed form
explains most of the adverse selection. H6 must first predict next week's
volatility, and weekly variance is close to unforecastable at this horizon.

**The closed form is an excellent measurement tool and a modest forecasting
one** — and still the best forecasting tool available here, which is the point.

### H6.2 DEFECT FOUND AND FIXED — the theory arm was handicapped

The first run had the analytical arm at RMSE 4,795 against a 1,489 baseline, a
catastrophic loss. It was a bug, not a result.

The scaling `analytical_now * (rv_forecast / rv_now)` was dividing by
`realized_vol_7d`, which the panel deliberately lags one week for use as a
feature. Weekly variance ranges over a factor of thirty, so dividing by the
wrong week inflated predictions by up to 33x. Rebuilding `rv_now` unlagged from
the daily series moved the theory arm from worst to first.

**Lesson worth keeping.** A feature matrix and a model input are different
objects with different timing requirements. The lag that makes a variable a
legitimate *feature* made it the wrong *denominator*, and the failure looked
exactly like a substantive result — the theory losing to ML, which is the
outcome the plan explicitly warned would be the less interesting one. Had the
prior been the other way round it might not have been questioned.

---

## Stage 7 — the allocation strategy ⚠️ H7

352 pool-weeks, 2023-03 to 2026-07. Weekly rebalance, full costs from the first
run, all predictions out-of-sample under the Stage 6 purged folds.

### 7.4 The engine: predict the components, not the total

H5 showed that pointing gradient boosting at next week's *net* return fails —
significantly worse than the historical mean. Predicting the two components
separately works, because they have different mechanisms and different best
models:

| Component | Model | Out-of-sample R² |
|---|---|---|
| LVR | σ²/8 with a HAR-RV variance forecast | **+0.126** |
| Fees | LightGBM on volume and liquidity features | **+0.084** |
| *Net, directly* | *LightGBM* | *−0.128* |

**Each arm beats its own baseline where the combined target does not.** That is
the argument for decomposing rather than regressing the thing you care about,
and it is a methodological result independent of whether the strategy makes
money.

The fee feature set was chosen on out-of-sample *fee-prediction* R² before any
backtest was run, and logged. Seven features scored −0.037 against +0.084 for
four; selecting on backtest performance instead would be exactly the
multiple-testing trap the deflated Sharpe exists to punish.

### 7.5 Result

| Strategy | ann. return | vol | Sharpe | max DD | turnover | invested | DSR |
|---|---|---|---|---|---|---|---|
| Strategy (net > 0.2%/wk) | **−4.0%** | 2.9% | −1.35 | −12.3% | 0.65 | 55.7% | 0.000 |
| Strategy (net > 0, equal) | −5.0% | 3.0% | −1.66 | −15.3% | 0.58 | 75.6% | 0.000 |
| Strategy (net > 0, prop.) | −5.2% | 3.0% | −1.72 | −16.0% | 0.68 | 75.6% | 0.000 |
| Equal-weight LP (passive) | −6.4% | 3.0% | −2.12 | −19.4% | 0.00 | 100% | 0.000 |
| Best single pool ex-post | −2.6% | 3.5% | −0.77 | −10.6% | 0.00 | 100% | 0.005 |
| Hold 50/50 tokens | **+8.2%** | 37.2% | 0.22 | −48.9% | 0.00 | 100% | 0.163 |
| 50/50 rebalanced weekly | **+10.8%** | 31.4% | 0.35 | −40.8% | 0.00 | 100% | 0.229 |

**The signal works. The activity does not.**

The strategy beats passive LP by **+2.46% annualised, t = 2.75, p = 0.0066** on
a paired weekly test, and cuts maximum drawdown from −19.4% to −12.3%. It sits
entirely in cash in 44% of weeks. So the forecast is doing real work: it
identifies when *not* to provide liquidity.

But it cannot make an unprofitable activity profitable. Every LP variant is
negative. Holding the tokens returned +8.2% over the same window against −4.0%
for the best strategy configuration.

**No strategy clears the deflated Sharpe bar.** Every `beats_null` is False,
including both token benchmarks. With 7 logged specifications and 176 weeks,
nothing here is distinguishable from the best of a small search.

### 7.8 CORRECTION — "the profit is not there to find" was too strong ⚠️

I wrote that the strategy "cannot make an unprofitable activity profitable"
and that "the profit isn't there to find". The second half is **wrong**, and
testing it against a perfect-foresight ceiling shows why the distinction matters.

**Two mandates, and they give opposite answers.**

| Regime | ceiling (perfect foresight) | Sharpe | beats deflated Sharpe? | our forecast | passive |
|---|---|---|---|---|---|
| **A — may hold cash** | **+7.1%** | **2.38** | **yes (prob 1.00)** | −3.1% | −6.4% |
| **B — must be invested weekly** | **+0.5%** | **0.14** | **no (prob 0.10)** | −5.1% | −6.4% |

**The option to sit out is worth 6.63 percentage points**, and it is worth
essentially all of the opportunity.

- **Under a forced mandate the answer really is no.** Even with perfect
  hindsight the ceiling is +0.5% at a Sharpe of 0.14, which does not clear the
  deflated Sharpe bar. The two pools move together, so choosing *between* them
  adds almost nothing. Selection is worthless here.
- **Under a flexible mandate the answer is yes.** The ceiling is +7.1% at a
  Sharpe of 2.38 with no drawdown, and it clears the bar decisively. **A
  profitable strategy exists.** Ours captures 25% of the available edge and
  still lands at −3.1%.

**The shape of the opportunity explains both.** Liquidity provision on these
pools is profitable in **30.7% of weeks, averaging +25% annualised**, and
loss-making in the other 69%, averaging −9.2%. Sitting out the bad weeks is the
entire game; picking the right pool during the good ones is a rounding error.

**So H7's negative result is a statement about forecast skill, not about the
opportunity.** The honest form: *a profitable timing strategy exists on this
universe — perfect foresight earns 7.1% at a Sharpe of 2.38 — and our forecast
recovers only a quarter of it, which is not enough to reach profitability.*

That is a materially different and more useful claim than "there is nothing
there", and it points at what would improve the work: better weekly volatility
forecasting, since that is what drives the LVR side of the timing decision.

### 7.6 H7 verdict — economically insignificant, and that is the finding

The plan permitted this outcome explicitly, and it is the honest one:
**advertised LP yields are systematically overstated, and a forecast-driven
allocation does not recover them.**

The nuance worth keeping is that the failure is not a failure of the model. The
model has genuine out-of-sample skill on both components and a significant edge
over passive provision. What it cannot do is overcome an activity where fees
cover 92-99% of adverse selection before costs. Avoidance shrinks the loss; it
does not create a profit.

### 7.7 Two defects found while running it

**Token benchmarks were identical.** "Hold 50/50" and "50/50 rebalanced"
returned exactly the same number, which is impossible — the first drifts as ETH
appreciates and the second does not. Cause: the price series passed in was the
*position value*, which is re-anchored to a fixed notional at every re-centring
and therefore barely moves. Replaced with the actual CEX price from the derived
layer, and the two benchmarks now differ as they must (+8.2% vs +10.8%).

**Fee model overfitted on seven features.** Out-of-sample R² was −0.037 in the
backtest against +0.084 in the standalone diagnostic. 352 pool-weeks does not
support seven features. Reduced to four, chosen on the prediction task.

---

## Robustness — subperiods and regimes

### R.1 The theory's slope is unstable across years; its level is not

H3 by calendar year:

| Period | n | beta | R² | p(beta=1) | ratio of totals |
|---|---|---|---|---|---|
| 2023 | 729 | **0.372** | 0.346 | 0.0000 | 0.941 |
| 2024 | 732 | 0.918 | 0.677 | 0.388 | 1.004 |
| 2025 | 729 | 0.763 | 0.550 | 0.052 | 0.993 |
| 2026 | 423 | 0.944 | 0.756 | 0.160 | 1.016 |
| **Full sample** | 2,613 | 0.810 | 0.618 | 0.0068 | 0.991 |

**The full-sample rejection of beta = 1 is driven by 2023.** In 2024 and 2026
the null cannot be rejected at all, and 2025 sits at the boundary. Meanwhile the
**level match is stable at 0.94-1.02 in every single year** — the theory always
gets the size of the transfer right, and only the slope wanders.

This materially softens the H3 headline. The right statement is not "the closed
form's sensitivity is wrong" but "its sensitivity was wrong in 2023 and has been
close to right since". Why 2023 differs is not established here; MEV
infrastructure and v3 liquidity distribution both changed substantially over the
sample, and attributing it would need work this project has not done.

### R.2 The deviation is concentrated in high volatility

Terciles of daily volatility:

| Regime | n | beta | R² | ratio |
|---|---|---|---|---|
| Calm | 872 | **0.963** | 0.392 | 1.147 |
| Middle | 871 | **0.965** | 0.150 | 1.056 |
| Volatile | 870 | **0.753** | 0.485 | 0.944 |

In calm and middle markets beta is within 4% of one. The entire deviation sits
in the volatile tercile.

That is exactly the frictional story in H3.2, now localised: `sigma^2/8` assumes
arbitrage is continuous and costless, and that assumption is close enough to
true when prices move slowly. When they move fast, gaps open faster than
arbitrageurs close them and part of every large move is never captured — so
realised extraction falls below the frictionless bound and the slope flattens.

**The theory holds where its assumptions hold.** That is a better result than a
uniform beta of 0.81, and it is a testable statement rather than a fudge.

---

## Robustness — MEV classification (Stage 4.3)

### R.3 DEFECT FOUND AND FIXED — leg span was measured against the wrong ruler

The classifier bounded the distance between a sandwich's two legs by their
`log_index` difference. That counts **every event in the block**, including logs
from unrelated contracts, so it is a poor proxy for "brackets the victim". The
sweep exposed it immediately: under `log_index` the estimate never converges.

| Max span | `log_index` | `pool_position` |
|---|---|---|
| 2 | 0 sandwiches, $0 | 4,420, $11.09m |
| 3 | 0, $0 | 5,086, $12.52m |
| 4 | 0, $0 | 5,319, $12.74m |
| 8 | 285, $0.40m | 5,491, $12.80m |
| 24 | 1,475, $4.59m | **5,515, $12.80m** |
| 64 | 2,606, $8.74m | 5,515, $12.80m |

A span of 4 finding **zero** sandwiches was the tell. Real searchers do bracket
their victim immediately in the pool's own swap sequence; they just do not
appear adjacent in a global log index that other contracts are also writing to.

Counting only this pool's swaps between the legs, the estimate **saturates by a
span of 8 and is exactly flat thereafter** — which is what a correctly specified
parameter looks like. Default changed to `pool_position`; `log_index` is kept as
an option so the robustness table can show why it is wrong.

### R.4 Sensitivity within the defensible range

| Reversal tolerance | n | attacker profit |
|---|---|---|
| 2% | 4,204 | $10.82m |
| 5% | 4,735 | $11.26m |
| **10% (baseline)** | **5,515** | **$12.80m** |
| 25% | 8,439 | $23.20m |
| 50% | 12,861 | $21.38m |
| 100% | 35,636 | **−$29.86m** |

Within the defensible range — reversal at or below 10%, span at or above 4 —
the estimate sits between **$10.8m and $12.8m, a 1.18x spread**. That is a
robust number.

Outside it the classifier degrades visibly, and the failure is self-announcing:
at 100% tolerance total attacker "profit" is **negative**, which no population
of real sandwiches can be. Loose matching is admitting ordinary two-way flow.

**Headline: ETH/USDC 5bp transferred roughly $12.8m to sandwich searchers over
43 months**, about $3.6m a year from a single pool.

### R.5 What this does and does not affect

Attribution is `neutral` (DECISIONS 4.2), so the LP-side cost in the
decomposition is zero under **every** rule tested. The MEV estimate matters for
the intensity covariate in the forecast model and for the standalone claim about
how much value searchers extract — not for the net-return table. So the one
number in this project with real specification risk is also the one the headline
does not rest on.

### R.6 Performance — the classifier was 47x slower than necessary

Profiling to make the sweep affordable found that `to_dict("records")` was being
called once per block: 125,418 calls costing 134 of 138 seconds, while the
pair-matching logic it wrapped was free. One conversion for the whole frame,
then grouping in pure Python, cut a month from 37.7s to 0.80s with identical
output. Worth recording because the first optimisation attempted — indexing
candidate pairs by sender — was aimed at the wrong thing and changed nothing;
profiling rather than guessing found it in one step.

---

## Robustness — position specification, and a labelling correction

### R.7 DEFECT FOUND AND FIXED — the headline was mislabelled "raw" ⚠️

`fees − LVR − gas` was reported throughout Stage 5 as the **raw** variant, with
a separate "hedged" column formed by subtracting perp funding. That is backwards.

LVR is *defined* as the P&L gap between the AMM position and a continuously
rebalanced portfolio holding the same delta, so

    AMM_return = rebalanced_return + fees − LVR

Subtracting the rebalanced portfolio is exactly what a delta hedge does, and
what remains is `fees − LVR`. **That quantity is already delta-hedged by
construction.** It carries no directional term at all.

**How it announced itself.** In the full-sample sweep the "hedged" series had
*higher* volatility than the "raw" one — 0.1714 against 0.1614. A hedge cannot
raise volatility. Chasing that impossibility found the labelling error.

**Three returns, now kept distinct:**

| Quantity | Definition | What it is |
|---|---|---|
| `net_market_making` | fees − LVR − gas | Delta-hedged under a frictionless hedge. **The headline.** |
| `net_hedged_implemented` | that, − perp funding − trading | What an LP could actually achieve |
| `total_return` | value change + fees − gas | Unhedged, directional beta intact |
| `rebalanced_return` | value change + LVR | The benchmark's own return; what a hedge removes |

with `total_return = rebalanced_return + net_market_making`, asserted per cohort
by `check_identity`.

One further subtlety the fix exposed: the position's **value change is not
purely directional** — by the identity it equals `rebalanced_return − LVR`, so
adverse selection is already inside it. Recovering the directional piece means
adding LVR back, not subtracting it.

**What this changes.** The headline numbers are unaffected in value: −9.10% and
−2.31% were always the delta-hedged market-making return, which is what Stage 0
chose to lead with. What changes is that they were described as the robustness
column when they were the headline, and the *actual* unhedged return was never
computed. It is now.

### R.8 Range width across the full sample — the corner solution holds

430 pool-months, both pools, five widths. Mean annualised market-making return:

| Requested | realised delta | mean re-centres | ETH/USDC 5bp | ETH/USDC 30bp | pooled CI |
|---|---|---|---|---|---|
| ±2% | 2.20% | 60.3 | **−64.36%** | −33.22% | [−70.1%, −30.8%] |
| ±5% | 5.19% | 12.6 | −20.13% | −7.83% | [−22.0%, −7.3%] |
| ±10% | 10.19% | 3.3 | −9.10% | −2.31% | [−10.0%, −2.2%] |
| ±25% | 25.71% | 0.36 | −3.65% | −0.66% | [−4.0%, −0.6%] |
| ±50% | 55.11% | 0.07 | −1.76% | −0.31% | [−1.9%, −0.3%] |

**Monotone in width, on both pools, across 43 months — and every confidence
interval excludes zero.** This is the corner solution Stage 8 predicted when
`kappa < 0`: fees and LVR scale together, so concentration cannot change the
sign, and the least-bad position is the widest one.

Confirming it on the full sample rather than one month matters, because January
2023 was a 40% trending month and the obvious objection was that the corner was
a property of that trend. It is not.

### R.10 Q3 REOPENED AND RE-CLOSED — the alignment rule matters after all ⚠️

Stage 1.5 closed open question 3 with "the rule earns a sentence, not a slide",
on the basis that the three alignment rules moved the mean pool-versus-CEX
*gap* by under 2bp on a 22bp base, in one month.

**That conclusion was wrong**, and re-testing on 15 months across both pools
shows why:

| Rule | mean LVR vs baseline | p5 | p95 | max deviation |
|---|---|---|---|---|
| Last trade at or before block ts (baseline) | 1.000 | — | — | — |
| One slot earlier | **0.817** | 0.717 | 0.917 | **31.0%** |
| Midpoint interpolation *(lookahead)* | 0.997 | 0.930 | 1.045 | 10.5% |

Using a reference one slot (12s) earlier **understates LVR by 18% on average and
by up to 31%**.

**Two reasons the earlier test missed it.** It measured the *price gap*, and LVR
is quadratic in the gap and accumulates along a path, so it is far more
sensitive than the gap's own mean. And one month is not 15.

**The mechanism, and it is economically meaningful.** Blocks are not uniformly
spaced — trading clusters immediately after a price move. A reference 1s before
the block captures the move that *triggered* the trade; one 13s before misses
it. So the understatement scales with how sparse the pool is:

| Pool | median inter-trade gap | share of gaps > 60s | LVR ratio |
|---|---|---|---|
| ETH/USDC 5bp | 12s | 1.9% | **0.878** |
| ETH/USDC 30bp | 48s | 44.3% | **0.755** |

The denser pool loses 12%, the sparser one 25%, exactly as the trigger story
predicts.

**This vindicates the baseline rather than undermining it.** The arbitrageur
*saw* the move that made the trade profitable, so the reference must sit after
it. A 13s-stale reference is not a more conservative choice — it is a
systematically biased one, and the bias is downward.

**Re-closed: baseline stands, and it now earns a robustness slide rather than a
sentence.** The lesson is that a robustness check has to be run on the quantity
being reported, not on a proxy for it.

### R.9 Hedge frequency — the cheapest hedge is the one that does not hedge

| Rebalance | net (implemented) | mean unhedged exposure | as % of notional |
|---|---|---|---|
| Hourly | −10.20% | $1,931 | 1.9% |
| Daily | −4.45% | $8,517 | 8.5% |
| Weekly | −3.24% | $15,038 | 15.0% |

Weekly looks best and is worst. Leaving 15% of a $100k position in naked delta
is not a saving, it is a failure to hedge — and the resulting number is
contaminated by exactly the directional beta the variant exists to remove.

The Q7 decision (hourly) stands, on a refined reason: hourly costs about 7
percentage points a year more in trading and funding, and buys an eightfold
reduction in tracking error. For a paper measuring market-making economics that
is the right trade. For an LP maximising realised return it might not be, and
the table says so.

Anything decided above and later changed goes here with the date and the
evidence that forced it. Empty is fine; silently editing an entry above is not.

| Date | Entry | Was | Now | Evidence |
|---|---|---|---|---|
| 2026-09-05 | Q1 MEV attribution | `flow_toxicity` leads | `neutral` leads | Walking the three legs from the LP's side: the LP round-trips, keeps ~the victim's inventory effect, and earns three fees instead of one. The toxicity channel is dynamic and not identified from one pool's swap log. See 4.2 |

## Step 2 — the crossover, and a reversal of the mechanism ⭐⭐

**The crossover cannot be located, and the reason is informative.**

Fitting `net = a + b·σ²` on 213 pool-months (ETH/USDC 100bp excluded as not a
price-taker) gives σ* = **43.5%**, but with a month-clustered 95% CI of
**[32.2%, 76.2%]** and **R² = 0.055**. Dropping the peg moves the point estimate
to 28.8% with R² = 0.013. The decile curve is not monotone: mean net is positive
in the two lowest deciles, negative through the middle, positive again around
41–46%, negative at the top. **There is no clean single crossing to report.**

### The reversal

The project carried the claim *"LVR scales with σ², fee income does not."*
**In this sample that is false.** Volume rises with volatility, so:

```
fees = +0.0427 + 3.0626·σ²   R² = 0.839
lvr  = -0.0033 + 3.2613·σ²   R² = 0.921
```

Both sides scale with variance, and at nearly the same rate. Net is the small
difference between two large, near-parallel terms — which is exactly why R² on
net is 0.055 and the crossover CI spans 44 points.

### Simpson's paradox

Across pools, `corr(σ, net) = −0.822` (5 fitted pools). **Within** pools the
slope on σ² is **+0.060, 95% CI [−0.242, +0.390], P(>0) = 0.65** — the sign
flips and it cannot be distinguished from zero. Per-pool slopes are positive in
4 of 5.

> The cross-pool result is a statement about **which pools happen to be
> volatile**, not about what volatility does to a given pool. "Volatility
> decides whether liquidity provision pays" is a between-pool association and
> must not be read as a mechanism.

This retracts the strong reading of `corr(σ, net) = −0.923` reported earlier
(itself now −0.568 on six pools, −0.822 on the five fitted).

### What actually separates the pools

`LVR/σ²` is **3.10–3.46 on every non-peg pool** and 41.8 on the peg — the same
breakdown of the diffusion at near-zero variance that H3 found. With the cost
side that stable, *"does this pool pay?"* reduces to *"is fee income per unit
variance above ~3.3?"*

Ranking on `fees/σ²` orders all five pools **perfectly** (Spearman +1.000)
against −0.900 for σ. Two caveats, both stated rather than buried: it is partly
mechanical, since `net = fees − LVR`; and lagged one month it does **not**
forecast better than the naive σ rule (76.2% vs 78.6% of months positive).

**The better cross-sectional descriptor is not the better forecast** — the same
conclusion the oracle decomposition reached from the other side. The binding
constraint is predicting fee income, not describing it after the fact.

## Step 3 — the static rule is retired ⭐⭐

The rule "always hold the lowest-σ pool" was the paper's only actionable
recommendation, reported at +6.4% and Sharpe 1.96. Three tests, and it fails all
three.

**First, that headline was not implementable.** +6.4% is *"always hold
USDC/USDT"* — a pool chosen with hindsight, before gas. Selecting on **lagged**
30-day volatility and charging gas gives **+4.31% at Sharpe 1.39** over 183
weeks. Gas alone is 1.16%/yr of the gap.

**1. Sharpe is measured against zero, not cash.** `deflated_sharpe_ratio` uses
`mean/sd` with no risk-free rate, but the position ties up real capital. FRED
was unreachable from this machine, so a sensitivity band is reported rather than
an invented series:

| risk-free | excess ann. | Sharpe | deflated p |
|---|---|---|---|
| 0% | +4.31% | 1.39 | 0.699 |
| 2% | +2.31% | 0.75 | 0.378 |
| **4%** | **+0.31%** | **0.10** | **0.082** |
| 5% | −0.69% | −0.22 | 0.023 |

At any plausible 2023–2026 cash rate the rule earns approximately nothing.

**2. It is not a volatility rule — it is one pool.** Walking down the σ ladder,
performance does not decay, it oscillates:

| rank by lagged σ | ann. | Sharpe | modal pool |
|---|---|---|---|
| 1 | +4.31% | 1.39 | USDC/USDT 1bp |
| 2 | **−1.17%** | −0.61 | WBTC/ETH 30bp |
| 3 | +2.63% | 0.59 | WBTC/USDC 30bp |
| 4 | −6.20% | −1.78 | ETH/USDC 5bp |

The second-lowest-σ pool **loses money**. A volatility mechanism would decay
monotonically. This is the same conclusion step 2 reached: σ ranks pools only
by coincidence of composition.

**3. It is regime-dependent.** 2023: −1.01%, positive in 12.5% of weeks. 2024–26:
+7.5%, +7.3%, +2.2%. First half Sharpe 0.76 (deflated 0.248), second half 2.66.

> **Retired.** The honest statement is *"the USDC/USDT pool paid well in
> 2024–2026 before financing costs"*, which is a description of one pool in one
> regime, not a rule. The paper should carry it as an observation with its
> failure modes stated, and should not recommend it.

This removes the project's last positive-Sharpe claim. What survives is the
measurement stack, H3's domain of validity, and the negative result about where
the edge is not.
