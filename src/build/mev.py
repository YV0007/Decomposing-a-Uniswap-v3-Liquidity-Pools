"""MEV classification and — the harder half — attribution to the LP.

Sandwich pattern, within one block by `log_index`::

    tx_A (searcher, direction D)  ->  tx_B (victim, direction D)  ->  tx_C (searcher, -D)

with A and C sent by the same address and moving the pool in opposite
directions, and at least one third-party swap between them.

Attribution is open question 1, and working the mechanics through changes the
answer
---------------------------------------------------------------------------
Walk a sandwich from the LP's side, leg by leg:

1. The attacker buys. The pool price rises; the LP sells some risky asset.
2. The victim buys at the worse price the attacker created. The LP sells more,
   at a *better* price than it would have got without leg 1.
3. The attacker sells back. The pool price returns to roughly where the
   victim alone would have left it, and the LP buys back.

The LP has done a round trip and ends with close to the inventory the victim
alone would have left it, having earned a fee on all three legs instead of one.
The direct P&L effect is therefore small and, if anything, positive. The victim
pays; the LP is not the counterparty being exploited.

That is why the working preference recorded in `DECISIONS.md` (flow toxicity as
the headline) is weaker than it first looked: the toxicity story is a *dynamic*
claim — that sandwiching degrades execution, which drives uninformed flow away
from the pool over time — and that is not identified from a single pool's swap
log. What is measurable is the intensity of the flow, so this module reports
that as a flow-quality covariate rather than dressing it up as a per-block cost.

Accordingly the three treatments here are: exclude the attacker legs from
"good" fee revenue, treat them as neutral, or carry sandwich intensity as a
feature. All three are computed; the headline uses the one argued for in
`DECISIONS.md` and the others bound it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pandas as pd

from src.utils.config import PoolSpec


class AttributionMethod(str, Enum):
    EXCLUDE_SANDWICH_VOLUME = "exclude_sandwich_volume"   # (a)
    NEUTRAL = "neutral"                                   # (b)
    FLOW_TOXICITY_COVARIATE = "flow_toxicity_covariate"   # (c)


@dataclass(frozen=True)
class Sandwich:
    block_number: int
    attacker: str
    front_log_index: int
    back_log_index: int
    victim_log_indices: tuple[int, ...]
    attacker_profit0: int          # base units, pool perspective negated
    attacker_profit1: int
    victim_volume0: int
    victim_volume1: int
    reversal_ratio: float


#: How closely the back leg must reverse the front leg for a pair to count as a
#: sandwich. A searcher unwinds essentially the whole front-run position; a pair
#: of unrelated trades from one address does not.
DEFAULT_REVERSAL_TOLERANCE = 0.10

#: Maximum `log_index` distance between the two legs. Sandwich legs bracket the
#: victim tightly; legs at opposite ends of a block are two separate trades.
DEFAULT_MAX_LEG_SPAN = 24


def _direction(amount0: int) -> int:
    """+1 when token0 flows into the pool, -1 when it flows out."""
    return 1 if amount0 > 0 else (-1 if amount0 < 0 else 0)


def _reversal_ratio(front: dict, back: dict) -> float:
    """How completely the back leg unwinds the front leg. 1.0 is exact.

    The attacker acquires whichever token flows *out* of the pool on the front
    leg, and returns it on the back leg. The ratio of those two quantities is
    the discriminator that same-address matching alone lacks.

    Without it the classifier fires on any address that happens to trade both
    ways in one block — routers, aggregators and market makers all do — which
    on ETH/USDC 5bp in January 2023 produced a set where 45% of "sandwiches"
    lost money and the top 1% of events carried 105% of the total profit.
    """
    f0, f1 = int(front["amount0"]), int(front["amount1"])
    b0, b1 = int(back["amount0"]), int(back["amount1"])
    if f0 < 0:                      # attacker received token0 on the front leg
        acquired, returned = -f0, b0
    elif f1 < 0:                    # attacker received token1
        acquired, returned = -f1, b1
    else:
        return 0.0
    if acquired <= 0 or returned <= 0:
        return 0.0
    return returned / acquired


def classify_sandwiches_by_address(
    swaps: pd.DataFrame, spec: PoolSpec,
    reversal_tolerance: float = DEFAULT_REVERSAL_TOLERANCE,
    max_leg_span: int = DEFAULT_MAX_LEG_SPAN,
    require_positive_profit: bool = True,
) -> pd.DataFrame:
    """Same-address, same-block, opposite-direction bracketing.

    Undercounts, because searchers rotate addresses between the front and back
    legs. Bundle-level identification would catch more, but the Flashbots
    public relay serves only recent slots and returns nothing for the sample
    period — so for 2023-2025 this bound is one-sided, and that is stated in the
    limitations rather than papered over.

    Matching is on `sender`, which for a router-mediated swap is the router.
    Same-address bracketing on its own is far too loose: three further
    constraints do the real work, and each is a parameter so Stage 4.3 can
    report sensitivity to all of them.

    - **Reversal.** The back leg must return within `reversal_tolerance` of what
      the front leg acquired. This is the constraint that separates a searcher
      from a router trading both ways in one block.
    - **Span.** The legs must sit within `max_leg_span` positions of each other.
      A sandwich brackets its victim; it does not span an entire block.
    - **Profit.** A sandwich is profitable by construction. Loss-making
      candidates are failed attempts at best and misclassifications at worst,
      and are excluded by default rather than allowed to net off the total.
    """
    if swaps.empty:
        return pd.DataFrame(columns=[f.name for f in Sandwich.__dataclass_fields__.values()])

    found: list[Sandwich] = []
    for block, grp in swaps.sort_values(["block_number", "log_index"]).groupby("block_number"):
        rows = grp.to_dict("records")
        used: set[int] = set()
        for i in range(len(rows)):
            if i in used:
                continue
            a = rows[i]
            for j in range(len(rows) - 1, i, -1):
                if j in used:
                    continue
                b = rows[j]
                if a["sender"] != b["sender"]:
                    continue
                if _direction(int(a["amount0"])) == 0:
                    continue
                if _direction(int(a["amount0"])) == _direction(int(b["amount0"])):
                    continue
                if int(b["log_index"]) - int(a["log_index"]) > max_leg_span:
                    continue
                ratio = _reversal_ratio(a, b)
                if not (1 - reversal_tolerance) <= ratio <= (1 + reversal_tolerance):
                    continue
                victims = [k for k in range(i + 1, j) if rows[k]["sender"] != a["sender"]]
                if not victims:
                    continue
                profit0 = -(int(a["amount0"]) + int(b["amount0"]))
                profit1 = -(int(a["amount1"]) + int(b["amount1"]))
                if require_positive_profit and profit0 <= 0 and profit1 <= 0:
                    continue
                found.append(
                    Sandwich(
                        block_number=int(block),
                        attacker=a["sender"],
                        front_log_index=int(a["log_index"]),
                        back_log_index=int(b["log_index"]),
                        victim_log_indices=tuple(int(rows[k]["log_index"]) for k in victims),
                        # Pool-perspective amounts negated: what the attacker netted.
                        attacker_profit0=profit0,
                        attacker_profit1=profit1,
                        victim_volume0=sum(abs(int(rows[k]["amount0"])) for k in victims),
                        victim_volume1=sum(abs(int(rows[k]["amount1"])) for k in victims),
                        reversal_ratio=ratio,
                    )
                )
                used.update({i, j, *victims})
                break
    return pd.DataFrame([s.__dict__ for s in found])


def sandwich_profit_usd(
    sandwiches: pd.DataFrame, spec: PoolSpec, price: Decimal
) -> pd.Series:
    """Attacker profit per sandwich in USD, at the prevailing pool price."""
    from src.build.position import token_usd_prices

    if sandwiches.empty:
        return pd.Series(dtype=object)
    p0, p1 = token_usd_prices(spec, price)
    return pd.Series(
        [
            Decimal(int(a0)) / Decimal(10**spec.token0.decimals) * p0
            + Decimal(int(a1)) / Decimal(10**spec.token1.decimals) * p1
            for a0, a1 in zip(sandwiches["attacker_profit0"], sandwiches["attacker_profit1"])
        ],
        index=sandwiches.index,
    )


def sandwich_intensity(swaps: pd.DataFrame, sandwiches: pd.DataFrame) -> dict:
    """Flow-quality metrics: how much of the pool's flow is searcher flow.

    This is the measurable part of the toxicity story. It enters the forecast
    model as a covariate (`mev_intensity_30d`) rather than the decomposition as
    a per-block cost, because the mechanism it proxies for is a dynamic effect
    on order-flow composition, not a direct transfer from the LP.
    """
    n_swaps = len(swaps)
    if n_swaps == 0:
        return {"n_swaps": 0, "n_sandwiches": 0, "attacker_swap_share": 0.0,
                "sandwiched_block_share": 0.0}
    n_attacker_legs = 2 * len(sandwiches)
    blocks = swaps["block_number"].nunique()
    return {
        "n_swaps": n_swaps,
        "n_sandwiches": len(sandwiches),
        "attacker_swap_share": n_attacker_legs / n_swaps,
        "sandwiched_block_share": (
            sandwiches["block_number"].nunique() / blocks if len(sandwiches) else 0.0
        ),
    }


def attribute_to_lp(
    sandwiches: pd.DataFrame, fee_rows: pd.DataFrame, spec: PoolSpec, price: Decimal,
    method: AttributionMethod = AttributionMethod.NEUTRAL,
) -> Decimal:
    """LP-side cost of observed MEV under the chosen treatment.

    - ``NEUTRAL`` — zero. The LP earns a fee on all three legs and ends with
      close to the inventory the victim alone would have left it. This is the
      defensible default for *direct* P&L.
    - ``EXCLUDE_SANDWICH_VOLUME`` — remove the fees earned on the attacker's two
      legs from fee revenue, on the view that this volume would not exist
      without the victim and should not be counted as organic income. The
      conservative bound.
    - ``FLOW_TOXICITY_COVARIATE`` — zero here by construction; the effect is
      carried as a forecasting feature, not a cost line.
    """
    if method is not AttributionMethod.EXCLUDE_SANDWICH_VOLUME or sandwiches.empty:
        return Decimal(0)

    attacker_legs = set()
    for blk, f, b in zip(sandwiches["block_number"], sandwiches["front_log_index"],
                         sandwiches["back_log_index"]):
        attacker_legs.add((int(blk), int(f)))
        attacker_legs.add((int(blk), int(b)))

    if "log_index" not in fee_rows.columns:
        raise ValueError("fee_rows must carry log_index to exclude attacker legs")
    mask = [
        (int(b), int(li)) in attacker_legs
        for b, li in zip(fee_rows["block_number"], fee_rows["log_index"])
    ]
    from src.build.fees import fees_to_usd

    sub = fee_rows[pd.Series(mask, index=fee_rows.index)]
    return fees_to_usd(int(sub["fee0"].sum()), int(sub["fee1"].sum()), spec, price)


def gate_sandwich_counts(
    intensity: dict, expected_share_range=(0.0005, 0.05), min_swaps: int = 5_000
) -> dict:
    """Stage 4 GATE: is the classifier firing sensibly where activity exists?

    The band applies only to pools with enough flow to be worth attacking.
    Zero sandwiches in a pool that saw 655 swaps in a month is the *correct*
    answer, not a classifier failure — sandwiching concentrates where the
    uninformed flow is, which on ETH/USDC in January 2023 meant the 5bp pool
    carried 241 of the 244 events found across all three tiers.

    Below the band on a busy pool means the constraints are too tight; above it
    means routers and market makers are being counted as searchers, which is
    what an unconstrained same-address rule does.
    """
    lo, hi = expected_share_range
    share = intensity["attacker_swap_share"]
    if intensity["n_swaps"] < min_swaps:
        return {
            "attacker_swap_share": share,
            "applicable": False,
            "passed": True,
            "note": f"only {intensity['n_swaps']:,} swaps; too thin to test the band",
        }
    return {
        "attacker_swap_share": share,
        "applicable": True,
        "in_expected_band": lo <= share <= hi,
        "passed": lo <= share <= hi,
    }
