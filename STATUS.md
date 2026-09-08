# Where the project stands — 8 September 2026

**52 commits · 266 tests passing · 75/75 deck checks · 11 GB · 6 pools · €0 spent**

The seven-step finishing plan is done through step 6. Step 7 (`reproduce.py
--full`) is running.

---

## The headline, after this round

The project set out to show that liquidity provision loses money once LVR is
counted. It ends somewhere more defensible and less comfortable:

> **Nothing in this project supports a positive-Sharpe LP strategy, and the
> mechanism we proposed for why some pools pay does not survive its own data.**

Three claims were retracted this round — each by a test the project ran on
itself, and each is now documented rather than quietly dropped.

### 1. "Volatility decides whether LPing pays" — retracted

`corr(σ, net)` was reported at −0.923 on four pools. It is **−0.568 on six**.
Adding WBTC/USDC broke the ordering: it earns **+4.09% at 40% σ**, more than
WBTC/ETH's +0.71% at 28% σ.

And the relationship is **Simpson's paradox**. Within a pool, the slope on σ² is
+0.060 with a CI of [−0.242, +0.390] — the sign flips and it cannot be
distinguished from zero. The cross-pool pattern says which pools *happen* to be
volatile, not what volatility does to a pool.

### 2. "LVR scales with σ², fee income does not" — false in this sample

```
fees = +0.043 + 3.06·σ²   R² = 0.839
LVR  = −0.003 + 3.26·σ²   R² = 0.921
```

Volume rises with volatility, so both sides scale with variance at nearly the
same rate. Net is the small difference between two large, near-parallel terms —
which is why net's R² on σ² is 0.055 and the crossover CI runs **[32.2%, 76.2%]**
around σ\* = 43.5%. **There is no well-determined crossover to report.**

What replaces it is narrower and better supported: `LVR/σ²` is **3.10–3.46 on
every non-peg pool**, so "does this pool pay?" reduces to "is `fees/σ²` above
~3.3?" That ranks all five pools perfectly — but it is partly mechanical, and
lagged a month it does **not** forecast better than the naive rule.

### 3. The static rule — retired

"+6.4% at Sharpe 1.96" was not implementable: it is "hold USDC/USDT", chosen
with hindsight, before gas. On lagged volatility with gas it is +4.31%/1.39, and
it fails three tests — worthless against a realistic cash rate (**+0.31% excess
at 4%**), not a volatility rule (**rank 2 loses money** while ranks 1 and 3 make
it), and regime-dependent (2023: −1.0%).

This removes the project's last positive-Sharpe claim.

---

## What survives, and is worth presenting

**The measurement stack.** Six pools reconstructed from an archive node with no
API keys, every layer gated against an independent source: prices against
on-chain state, fees against `feeGrowthInside`, LVR three independent ways.

**σ²/8 has a measured bias curve.** Realised/predicted runs monotonically from
**2.09** at the peg through unbiased around σ ≈ 0.6–0.9 to **0.76** in the top 1%
of days. The two failures previously reported separately are the two ends of one
curve.

**2023 is solved.** β = 0.372 vs 0.918–0.944 was **two days** — 17–18 August
2023. Drop the top 1% of σ days and 2023 becomes 0.779. Three explanations were
tested and *refused* (fee band, jumps, oversampling); range exhaustion is the
open candidate and is labelled as such.

**The negative result is the real finding.** Perfect volatility forecasting is
worth **0.9pp**; perfect fee forecasting **11.4pp — 80% of the gap to the
ceiling**. This is a volume-forecasting problem wearing a volatility costume,
and that is why a theory about the cost side does not become a strategy.

---

## Defects found this round

- **A stale fee cache** gave WBTC/USDC zero fees for 188 weeks and a −57% annual
  return. Caught only because the monthly decomposition independently said
  +4.09%. Now guarded, with nine regression tests.
- **`reproduce.py` silently lost its own test count** — `addopts = "-q"` plus a
  second `-q` made pytest `-qq` and dropped the summary line. It now stops
  rather than printing "no result".
- **The deck audit caught a number I had written from an ad-hoc filter** (0.961
  where the committed table says 0.958). It grew from 44 checks to **75**.

## Remaining

Step 7 only: the full rebuild from raw data, then a final commit.
