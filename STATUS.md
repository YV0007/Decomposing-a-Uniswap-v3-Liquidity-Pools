# Where the project stands — 8 September 2026

**46 commits · all tests passing · 11 GB of data · 6 pools · 3 asset pairs + a peg · €0 spent**

---

## 1. The measurement stack (Stages 1–4) — done and gated

Every layer is reconstructed from primary sources and checked against an
independent one before anything is built on top of it.

| Stage | What it does | Gate |
|---|---|---|
| 1 | Pool state from `sqrtPriceX96`, exact integer tick math | price reconstruction matches on-chain |
| 1.3 | Block↔CEX alignment, causality respected | no lookahead |
| 2 | Fee accrual per position | matches `feeGrowthInside` read on-chain |
| 3 | LVR three independent ways | sanity gate |
| 4 | MEV classification (sandwiches, arbitrage) | reversal/span/profit constraints |

No API keys were ever needed: Dune was replaced by a raw archive node, The Graph
by reading `feeGrowthGlobal`/`balanceOf` directly, Etherscan by RPC.

## 2. The economics (Stages 5–8, H1–H7) — done

The decomposition, the closed form, the forecast horse race, the allocation
backtest, and optimal range width all ran full-sample with purged/embargoed CV,
Newey–West errors, deflated Sharpe ratios and block-bootstrap CIs.

## 3. The two results that actually matter

**(a) The project's own central claim was falsified — by design.**

The stated falsification test was *"a pool where fees persistently exceed LVR by
more than costs."* USDC/USDT 1bp meets it: **+8.43% a year, CI [+5.0%, +11.6%],
profitable in 83% of months**, at a size holding ~0.00% of active liquidity, so
it is not a capacity artefact. `corr(σ, net return) = −0.923`.

> Liquidity provision pays where fee income covers adverse selection, and
> volatility decides whether it does. LVR scales with σ²; fee income does not.

**(b) The strategy is a volume-forecasting problem, not a volatility one.**

Decomposing the gap to the oracle ceiling: perfect volatility forecasting is
worth **0.9pp**; perfect fee forecasting is worth **11.4pp — 80% of the gap.**
That is why the theory does not convert into a strategy: σ²/8 predicts the cost
side well and says nothing about the income side, and the income side is where
the uncertainty lives.

## 4. Last two work items — both now complete

**Item 2 — better volatility forecasting.** Six-model race on 1,226 days,
scored on QLIKE as well as RMSE. **HAR-Q wins on both** (R² 0.114 → 0.157).
Implied volatility helps RMSE and hurts QLIKE — it works on average days and
fails in the tails. HAR-CJ is the *worst* HAR variant: separating jumps helps
explain what LVR *is*, not how much variance is coming. Kept as the baseline,
but recorded as an improvement to the measurement, not the strategy — it moved
the captured edge only from 9% to 10%, which is what led to result 3(b).

**Item 1 — the second major cross.** Added **WBTC/USDC 30bp**, verified
on-chain, 43 months of swaps and 3.8 GB of BTCUSDT 1-second klines.

Its purpose was to narrow the profitability crossover, which three pools had
bracketed only between 28% and 52% annualised volatility. **It lands at 40.0%
median σ — inside the bracket, exactly as intended.**

| Pool | median σ | β | R² | p(β=1) | level match |
|---|---|---|---|---|---|
| USDC/USDT 1bp | 2.3% | 0.634 | 0.002 | 0.000 | 6.60 |
| WBTC/ETH 30bp | 28.3% | 0.956 | 0.628 | 0.644 | 1.031 |
| **WBTC/USDC 30bp** | **40.0%** | **0.666** | **0.487** | 0.007 | **1.015** |
| ETH/USDC 5bp | 52.3% | 0.784 | 0.618 | 0.015 | 0.972 |
| ETH/USDC 30bp | 52.4% | 0.838 | 0.619 | 0.143 | 1.011 |
| ETH/USDC 100bp | 53.1% | 1.012 | 0.504 | 0.948 | 1.335 |

The closed form's **level** match on the new pool is the best in the sample
(1.5%), while its slope β sits below 1 — the same degradation-with-volatility
pattern already found twice independently.

Across six pools the LVR-per-variance slope moves **1.50× over a 100× fee
range**, so the finding that a fee band does not reduce LVR survives.

---

## 5. Running right now

`stage5_fullsample.py` on all six pools — the decomposition that turns WBTC/USDC
from a σ estimate into a **net return**, which is the number that actually
narrows the crossover. It is on pool 1 of 6; ETA roughly an hour.

## 6. What remains after that

1. **Place the crossover.** With a point at 40% σ, say where net return crosses
   zero instead of quoting a 28–52% bracket.
2. **Strengthen the static rule.** "Always hold the lowest-σ pool" earns +6.4% at
   Sharpe 1.96 but scores 0.83 against a 0.95 deflated-Sharpe bar, on one peg
   pool over 177 weeks. Suggestive, not established.
3. **Explain 2023.** β is 0.372 there against 0.918–0.944 in later years —
   currently unexplained.
4. **Fold both new results into DECK.md and DECISIONS.md**, then re-run
   `audit_deck.py` (44 checks) so no slide can drift from its table.
