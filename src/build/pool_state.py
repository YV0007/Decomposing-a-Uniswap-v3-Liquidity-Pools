"""Block-level pool state reconstructed from raw Swap logs.

The output is the spine of everything downstream: for every block in which the
pool traded, its closing price, tick, active liquidity and volume. Stage 1's
GO/NO-GO gate is a check on the price column produced here.

Price comes from `sqrtPriceX96` via `src.utils.precision` and nowhere else. The
`tick` field on the same event is deliberately *not* used to produce the price —
it is held back as an independent cross-check, since the pool emits both and
they must agree by construction.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.utils import precision as pr
from src.utils.config import PoolSpec


def build_pool_state(swaps: pd.DataFrame, spec: PoolSpec) -> pd.DataFrame:
    """Collapse the swap log to one row per block.

    Within a block the closing state is the last swap by `log_index` — the
    canonical on-chain ordering. The intra-block price path is discarded here
    and recovered in `mev.py`, which needs the ordering; keeping both views in
    one frame invites accidental use of the wrong one.

    `swaps` must carry big integers as Python ``int`` (see
    `rpc_client.load_big_ints`), not as int64 or float64.
    """
    if swaps.empty:
        return pd.DataFrame()

    df = swaps.sort_values(["block_number", "log_index"])

    # Closing state of each block = last swap in it.
    close = df.groupby("block_number", as_index=False).last()

    # Volumes: absolute token flow across every swap in the block.
    vol = (
        df.assign(v0=df["amount0"].map(abs), v1=df["amount1"].map(abs))
        .groupby("block_number", as_index=False)
        .agg(volume0=("v0", "sum"), volume1=("v1", "sum"), n_swaps=("log_index", "size"))
    )

    state = close.merge(vol, on="block_number", how="left")

    # Price via the precision module. Never a local formula.
    state["price"] = state["sqrt_price_x96"].map(
        lambda s: pr.sqrt_price_x96_to_price(
            int(s), spec.token0.decimals, spec.token1.decimals, spec.invert_price
        )
    )
    return state[
        ["block_number", "block_timestamp", "log_index", "tx_hash", "sqrt_price_x96",
         "tick", "liquidity", "price", "volume0", "volume1", "n_swaps"]
    ].reset_index(drop=True)


def attach_block_times(state: pd.DataFrame, block_times: dict[int, int]) -> pd.DataFrame:
    """Attach block timestamps (unix seconds) and a UTC datetime column."""
    out = state.copy()
    out["block_time"] = out["block_number"].map(block_times)
    out["block_dt"] = pd.to_datetime(out["block_time"], unit="s", utc=True)
    return out


def forward_fill_to_block_grid(state: pd.DataFrame, all_blocks: pd.DataFrame) -> pd.DataFrame:
    """Extend to every block, including those with no swap.

    A pool with no trade in a block still holds a stale price, and staleness is
    the mechanism being measured — so blocks without swaps are the interesting
    ones, not rows to drop. Fill forward only; a backward fill is lookahead.
    """
    merged = all_blocks.merge(state, on="block_number", how="left")
    carry = ["sqrt_price_x96", "tick", "liquidity", "price"]
    merged[carry] = merged[carry].ffill()
    for col in ("volume0", "volume1", "n_swaps"):
        merged[col] = merged[col].fillna(0)
    merged["traded"] = merged["n_swaps"] > 0
    return merged


# --------------------------------------------------------------------------- #
# Stage 1 gate
# --------------------------------------------------------------------------- #

def check_price_against_tick(state: pd.DataFrame, spec: PoolSpec) -> pd.DataFrame:
    """Cross-check the decoded price against the pool's own `tick` field.

    The pool emits both `sqrtPriceX96` and `tick` in every Swap, and `tick` is
    by definition ``floor(log_1.0001(raw_price))``. So the raw price must sit in
    ``[1.0001**tick, 1.0001**(tick+1))`` — a band exactly one tick wide, i.e.
    1 basis point.

    This is a far tighter test than comparing to an external price feed, and it
    isolates the thing being tested: the decode and the precision path. An
    external comparison would conflate reconstruction error with genuine
    pool-versus-CEX divergence, which is the quantity the paper measures and
    must not be assumed away here.

    Returns per-row `position_in_tick` in [0, 1); anything outside means the
    decode, the decimals or the precision path is wrong.
    """
    rows = []
    for sqrt_x96, tick in zip(state["sqrt_price_x96"], state["tick"]):
        raw = pr.raw_price_from_sqrt_price_x96(int(sqrt_x96))
        lo = pr.tick_to_raw_price(int(tick))
        hi = pr.tick_to_raw_price(int(tick) + 1)
        rows.append(
            {
                "tick": int(tick),
                "raw_price": raw,
                "tick_lower_price": lo,
                "position_in_tick": (raw - lo) / (hi - lo),
                "in_band": lo <= raw < hi,
            }
        )
    return pd.DataFrame(rows)


def gate_price_reconstruction(state: pd.DataFrame, spec: PoolSpec) -> dict:
    """Stage 1 GO/NO-GO.

    Every reconstructed price must lie inside the one-basis-point band implied
    by the tick the pool itself reported. A failure means stop: the usual
    causes, in order of frequency, are token0/token1 inverted, decimals not
    applied, and float64 in the price path.
    """
    check = check_price_against_tick(state, spec)
    n_bad = int((~check["in_band"]).sum())
    return {
        "n_rows": len(check),
        "n_outside_tick_band": n_bad,
        "max_position_in_tick": float(check["position_in_tick"].max()),
        "min_position_in_tick": float(check["position_in_tick"].min()),
        "passed": n_bad == 0,
        "detail": check,
    }
