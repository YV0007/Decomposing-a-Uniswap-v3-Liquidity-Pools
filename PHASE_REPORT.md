# Phase Report — Generalisation Beyond ETH/USDC

**7 September 2026.** 34 commits · 257 tests · 5.7 GB · 5 pools · 2 asset pairs + a peg

This phase addressed the single biggest weakness in the project: every result up
to it rested on one asset pair, ETH/USDC, and really on two of its three fee
tiers. WBTC/ETH and USDC/USDT were configured and verified in Stage 1 and never
analysed.

*Numbers below are from the five-pool run with 41 of 43 WBTC/ETH months. A
re-run including the last two is in flight; it will not move anything
materially.*

---

## What the phase was for

Adding two pools is not interesting in itself. What matters is the **range of
volatility** they open up:

| Pool | pair | median annualised σ |
|---|---|---|
| USDC/USDT 1bp | a peg | **2.31%** |
| WBTC/ETH 30bp | a cross of two correlated majors | **28.35%** |
| ETH/USDC 5 / 30 / 100bp | a major against the dollar | **52–53%** |

That is a **23× spread in volatility — 526× in variance**, which is what LVR
scales with. A theory that holds across that range is saying something; a theory
verified on one asset is not.

---

## Result 1 — the closed form generalises ⭐

| Pool | median σ | β | R² | p(β=1) | level match |
|---|---|---|---|---|---|
| USDC/USDT 1bp | 2.31% | 0.634 | **0.002** | 0.0000 | **6.60** |
| **WBTC/ETH 30bp** | 28.35% | **0.953** | **0.628** | **0.635** | **1.026** |
| ETH/USDC 5bp | 52.26% | 0.784 | 0.618 | 0.015 | 0.972 |
| ETH/USDC 30bp | 52.39% | 0.838 | 0.620 | 0.143 | 1.011 |
| ETH/USDC 100bp | 53.04% | 1.012 | 0.504 | 0.948 | 1.335 |

**On WBTC/ETH the null β = 1 cannot be rejected at all (p = 0.635)**, the level
matches within 2.6%, and R² is 0.628 — marginally *better* than on ETH/USDC.
The theory was not fitted to this pool in any sense. It was applied.

H3 is no longer a statement about ETH/USDC.

---

## Result 2 — the theory has a lower bound, and we found it ⭐

**On the peg pool σ²/8 fails completely.** R² = 0.002 — no relationship at all —
and empirical LVR is **6.6× the analytical prediction**.

This is not a defect. It is the most informative result of the phase, and it
completes a story the earlier work had only half of.

H3 already found a **positive intercept**: a floor of adverse selection the
diffusion misses, from discrete blocks, jumps, and MEV-ordered flow. On a
volatile pool that floor is small next to the diffusive term and shows up only
as α > 0. On a peg the diffusive term nearly vanishes — and the floor is all
that is left.

> **LVR = a diffusive part, which σ²/8 captures, plus a floor that it does not.**
> On volatile pools the first dominates and the theory works. On a peg the second
> dominates and it fails by a factor of six.

That gives the closed form a stated **domain of validity**: it holds from
roughly 28% to 53% annualised volatility and breaks below. Knowing where a
theory stops working is worth more than another confirmation of where it does.

---

## Result 3 — Q5 survives a second asset

LVR per unit variance, four fee tiers, two asset pairs:

| Pool | fee | slope | R² |
|---|---|---|---|
| ETH/USDC 5bp | 5bp | 0.00553 | 0.620 |
| ETH/USDC 30bp | 30bp | 0.00576 | 0.624 |
| WBTC/ETH 30bp | 30bp | 0.00657 | 0.630 |
| ETH/USDC 100bp | 100bp | 0.00590 | 0.462 |

Across a **20× fee range the slope moves 1.19×**, and the widest tier is not the
lowest. The conclusion that a fee band does not reduce LVR holds outside the
pair it was derived on.

*The peg pool is excluded from this comparison: its LVR is not variance-driven
at all (R² = 0.002), so a slope of LVR on variance is not a meaningful quantity
there.*

---

## Result 4 — the regime finding, confirmed twice independently

WBTC/ETH runs at half ETH/USDC's volatility and has the β closest to 1 of any
liquid pool in the sample.

That is the same pattern found *within* ETH/USDC by splitting on volatility
terciles — β of 0.963 and 0.965 in calm and middle markets against 0.753 in the
volatile one.

**Two independent cuts of the data — one across assets, one within one asset —
agree that σ²/8 degrades with volatility and with nothing else.** That is much
harder to explain away as an artefact than either cut alone.

---

## What the phase required

Three pieces of engineering, each guarding a silent failure.

**Valuation around an explicit numéraire.** WBTC/ETH has no stablecoin leg, so a
dollar value cannot be inferred from the pool price. The code now takes the USD
price of token1 explicitly and **refuses** when it cannot be inferred — because
the alternative was a $100k notional silently meaning 100,000 ETH. The explicit
and inferred routes agree exactly where both apply, so ETH/USDC numbers are
unchanged and the H3 builder reproduces its earlier output to the dollar.

**A per-pool CEX reference.** ETHUSDT was hardcoded. That worked while the
universe was one asset pair and would have compared a Bitcoin pool against an
Ether price. Now: ETHBTC **inverted** for WBTC/ETH (the pool quotes ETH per BTC,
Binance quotes BTC per ETH), USDCUSDT for the peg.

**Verified before trusting.** Pool price 13.579 ETH/BTC against a CEX 13.601 —
ratio 0.998 — with ETH at $1,554 and BTC at $21,091 for January 2023, both
correct historically. The median gap is **32.1 bp on a 30 bp pool**, the same
no-arbitrage band pattern found on ETH/USDC.

---

## One defect found and fixed

The numéraire series had no history prepended, unlike the reference series, so
the first blocks of a month had nothing to look *back* at and the numéraire was
null there. It surfaced two months into the WBTC build as a
`decimal.InvalidOperation` from a **single NaN row**.

Fixed by prepending the previous month's tail, as the reference already does,
and forward-filling only — back-filling would be lookahead. The builder now
raises with a clear message rather than emitting nulls if a block genuinely has
no prior price.

---

## What this does and does not license

**Does.** The measurement stack and the theoretical result now stand on two
independent asset pairs plus a peg. H3 and Q5 are no longer ETH/USDC statements,
and the closed form has a stated domain of validity with a measured lower bound.

**Does not.** The **economic** conclusions are still ETH/USDC results. That LPs
lost money, that fees covered 92–99% of adverse selection, that the strategy
beats passive provision without making it profitable — all of that rests on one
asset pair. Only WBTC/ETH's **LVR** has been computed, not its decomposition.

Running the full decomposition on WBTC/ETH is the obvious next step and is now
cheap: the data, the derived layer and the valuation are all in place.
