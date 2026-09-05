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

Measured on a +/-10% position, January 2023: **1.19x**, i.e. the textbook form
understates LVR by 16%. Both are reported.

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

## Log of reversals

Anything decided above and later changed goes here with the date and the
evidence that forced it. Empty is fine; silently editing an entry above is not.

| Date | Entry | Was | Now | Evidence |
|---|---|---|---|---|
| 2026-09-05 | Q1 MEV attribution | `flow_toxicity` leads | `neutral` leads | Walking the three legs from the LP's side: the LP round-trips, keeps ~the victim's inventory effect, and earns three fees instead of one. The toxicity channel is dynamic and not identified from one pool's swap log. See 4.2 |
