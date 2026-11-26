# Project complete — 8 September 2026

**56 commits · 266 tests passing · 80/80 deck checks · `reproduce.py --full` green end to end · 6 pools · 11 GB · €0**

Every planned stage, both extension phases, the seven-step finishing plan and one
extra question are closed. The deliverable is
[`outputs/paper/LVR_MEV_WorkingPaper.pdf`](outputs/paper/LVR_MEV_WorkingPaper.pdf),
an 11-page working paper that regenerates from the output tables.

---

## The result

> **The cost of providing liquidity is now measurable without assumption; the
> return to it is not forecastable, and the two facts have the same cause.**

σ²/8 prices the cost side well — ~62% of daily variation with zero fitted
parameters, beating gradient boosting at p < 0.0001 — and says nothing about the
income side, which is where the uncertainty lives. Perfect variance forecasting
is worth **0.9pp**; perfect fee forecasting **11.4pp**.

## What stands

| | |
|---|---|
| **Liquidity provision is not uniformly loss-making** | Two of five pools pay: USDC/USDT **+8.43%**, WBTC/USDC **+4.09%**. This met the project's own falsification test. |
| **σ²/8 has a measured bias curve** | Realised/predicted runs **2.09 → 0.76** monotonically in σ. Both previously separate failures are the ends of one curve. |
| **Theory beats ML** | Only model with positive OOS R² (+0.126); Diebold–Mariano p < 0.0001. |
| **A fee band does not reduce LVR** | Across a 100× fee range the slope moves 1.50×. |
| **No strategy clears the bar** | Nothing reaches a 0.95 deflated Sharpe. |

## What was retracted — each by a test the project ran on itself

| Retracted | Replaced by |
|---|---|
| `corr(σ, net) = −0.923` | −0.568 on six pools; **within** pools the slope's CI spans zero — Simpson's paradox |
| "LVR scales with σ², fee income does not" | Both scale with σ² at nearly the same rate (3.06 vs 3.26) |
| "A static rule earns +6.4% at Sharpe 1.96" | Not implementable; ~0 against a realistic cash rate; **rank 2 on the σ ladder loses money** |
| "Range exhaustion explains extreme days" | Refuted **backwards**: trending days score 1.261, oscillating days 0.780 |

The last one produced the project's final positive finding: the over-prediction
sits on days that **travel a long way without going anywhere**. A pool can be
arbitraged at most once per block and movement below the round-trip cost is
never arbitraged, so oscillation generates variance no arbitrageur can convert
into profit. Four of four candidate mechanisms were tested and refused; the shape
effect needed none of them.

## Defects found, all now guarded by tests

| Defect | Why it was invisible |
|---|---|
| A stale cache gave one pool **zero fees for 188 weeks** (−57%/yr) | Zero is a valid fee. Caught only because the monthly decomposition independently said +4.09% |
| `int24` decoded at the declared width | Invisible on ETH/USDC, universal on the peg. Caught by a columnar writer refusing the integer |
| The hedge shorted ETH against a dollar delta | Funding reached −9,856% of notional |
| `reproduce.py` lost its own test count | `addopts="-q"` plus a second `-q` makes pytest `-qq` |
| The central figure asserted a retracted claim | Caught while typesetting the paper |

## What is genuinely left

Nothing on the plan. Three extensions, none of which any conclusion depends on:

1. **A realised risk-free series** — FRED is unreachable from this machine, so
   the static rule's retirement rests on a sensitivity band.
2. **A seventh pool between 2.3% and 28.3% σ** — that region is unobserved.
3. **A Dune key** — the only place one would help is bundle-level MEV, which the
   public Flashbots relay cannot serve for 2023. MEV magnitudes are a one-sided
   undercount without it.
