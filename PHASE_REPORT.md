# Phase Report — Generalisation Beyond ETH/USDC

> **Superseded in part — read with DECISIONS.md steps 2–4.** This report is kept
> as the record of that phase. Three of its conclusions were later overturned by
> work it made possible:
>
> - **`corr(σ, net) = −0.923` is retracted.** It is −0.568 across six pools, and
>   the relationship does not reproduce *within* pools (slope +0.060, CI spanning
>   zero) — a Simpson's paradox.
> - **"LVR scales with σ², fee income does not" is false in this sample.** Both
>   scale with σ² at nearly the same rate; pools differ in fee income per unit
>   variance.
> - **The static rule is retired.** It is not implementable as quoted, earns
>   nothing against a realistic cash rate, and is not a volatility rule.
>
> The measurement work, the numéraire and hedge-map defects, and the falsification
> of the "LPs always lose" claim all stand.

**7 September 2026.** 34 commits · 257 tests · 5.7 GB · 5 pools · 2 asset pairs + a peg

This phase addressed the single biggest weakness in the project: every result up
to it rested on one asset pair, ETH/USDC, and really on two of its three fee
tiers. WBTC/ETH and USDC/USDT were configured and verified in Stage 1 and never
analysed.

*Final numbers, all 43 WBTC/ETH months. The two months that initially failed on
a numéraire gap (see below) moved every figure only in the third decimal.*

---

## What the phase was for

Adding two pools is not interesting in itself. What matters is the **range of
volatility** they open up:

| Pool | pair | median annualised σ |
|---|---|---|
| USDC/USDT 1bp | a peg | **2.31%** |
| WBTC/ETH 30bp | a cross of two correlated majors | **28.28%** |
| ETH/USDC 5 / 30 / 100bp | a major against the dollar | **52–53%** |

That is a **23× spread in volatility — 528× in variance**, which is what LVR
scales with. A theory that holds across that range is saying something; a theory
verified on one asset is not.

---

## Result 1 — the closed form generalises ⭐

| Pool | median σ | β | R² | p(β=1) | level match |
|---|---|---|---|---|---|
| USDC/USDT 1bp | 2.31% | 0.634 | **0.002** | 0.0000 | **6.60** |
| **WBTC/ETH 30bp** | 28.28% | **0.956** | **0.628** | **0.644** | **1.031** |
| ETH/USDC 5bp | 52.26% | 0.784 | 0.618 | 0.015 | 0.972 |
| ETH/USDC 30bp | 52.39% | 0.838 | 0.620 | 0.143 | 1.011 |
| ETH/USDC 100bp | 53.04% | 1.012 | 0.504 | 0.948 | 1.335 |

**On WBTC/ETH the null β = 1 cannot be rejected at all (p = 0.644)**, the level
matches within 3.1%, and R² is 0.628 — marginally *better* than on ETH/USDC.
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
| WBTC/ETH 30bp | 30bp | 0.00660 | 0.630 |
| ETH/USDC 100bp | 100bp | 0.00590 | 0.462 |

Across a **20× fee range the slope moves 1.19×**, and the widest tier is not the
lowest. The conclusion that a fee band does not reduce LVR holds outside the
pair it was derived on.

*The peg pool is excluded from this comparison: its LVR is not variance-driven
at all (R² = 0.002), so a slope of LVR on variance is not a meaningful quantity
there.*

---

## Result 4 — the regime finding, confirmed twice independently

WBTC/ETH runs at half ETH/USDC's volatility (28.3% against 52–53%) and has the
β closest to 1 of any liquid pool in the sample.

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

## Result 5 — the decomposition, and the central claim falls ⭐⭐

*Added after the initial report: the full decomposition was then run on all five
pools, which is what the phase existed to make possible.*

| Pool | median σ | fees | LVR | **fees/LVR** | **net** | 95% CI | months > 0 |
|---|---|---|---|---|---|---|---|
| **USDC/USDT 1bp** | **2.3%** | +10.3% | −1.6% | **6.49** | **+8.43%** | **[+5.0%, +11.6%]** | **83%** |
| WBTC/ETH 30bp | 28.3% | +32.8% | −31.5% | 1.04 | +0.71% | [−1.6%, +3.4%] | 44% |
| ETH/USDC 5bp | 52.3% | +88.8% | −96.8% | 0.92 | −9.10% | [−15.6%, −3.3%] | 26% |
| ETH/USDC 30bp | 52.4% | +96.7% | −97.9% | 0.99 | −2.31% | [−5.2%, +1.3%] | 21% |

**`corr(σ, net return) = −0.923`.** The project's stated falsification test —
*a pool where fees persistently exceed LVR by more than costs* — was met.
USDC/USDT is significantly profitable at a size where the LP holds ~0.00% of
active liquidity, so it is not a capacity artefact.

> **Liquidity provision pays where fee income covers adverse selection, and
> volatility decides whether it does.** LVR scales with σ², fee income does not.

The old claim was true of the pools measured and false as a general statement.
**This is exactly the failure mode the phase was built to test**, and the phase
found it.

### And it reframed the strategy

Re-running the allocation over four pools:

| Strategy | ann. return | Sharpe | deflated Sharpe |
|---|---|---|---|
| Oracle — perfect foresight | **+14.6%** | **3.96** | passes |
| **Static: always the lowest-σ pool** | **+6.4%** | **1.96** | 0.83 |
| Our forecast | +0.1% | 0.03 | 0.06 |
| Passive equal-weight | −1.4% | −0.68 | 0.00 |

A static, theory-derived rule beats the model sixtyfold. **The actionable
conclusion is a rule, not a model** — consistent with H5 and H6 throughout.

## Two further defects the phase exposed

**The hedge did not know what it was hedging.** It shorted an ETH perp against
whatever `risky_delta` returned — the WBTC holding on one pool and the USDC
holding on another — producing funding of **−9,856% of notional**. Pools now
declare which legs carry USD price risk: two-leg for WBTC/ETH, none for the peg.

**Raw σ²/8 used as a forecast inherits its bias.** Predicted LVR fell short of
realised on every pool, and in dollars the shortfall scaled with LVR itself —
$325 a week on ETH/USDC 30bp against $28 on the peg — which flattered the
volatile pools by ~17% a year and made the model rank them first, picking the
true best pool only 31% of the time. Calibrating within training folds only
lifted the strategy from −0.7% to +0.1%.

## What this does and does not license

**Does.** The measurement stack, the theoretical result *and* the economic
conclusion now stand on three asset pairs across a 23× volatility range. The
central claim is no longer about ETH/USDC.

**Does not.** Three points do not locate the crossover: we know only that it
sits between 28% and 52% annualised. The static rule is the paper's actionable
recommendation and scores 0.83 against a 0.95 deflated-Sharpe bar on a single
peg pool over 177 weeks — suggestive, not established.
