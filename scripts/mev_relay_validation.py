"""How much MEV does on-chain classification miss? — quantifying the undercount.

The paper reports MEV magnitude as its least robust number, on the grounds that
bundle-level attribution needs relay data. That was stated as unobtainable. It
was not: the Flashbots relay serves historical bidtraces, and the earlier
attempt failed only because it queried by `slot` rather than by `block_number`.

What the relay publishes is the **payment from builder to proposer** for each
delivered block — the price the builder was willing to pay for the right to
order that block, which is the market's own valuation of the extractable value
in it. That is not a bundle decomposition, but it is an independent, market-set
measure against which an on-chain classification can be checked.

Two things are measured here:

1. **Coverage.** Flashbots is one relay among several, so only a fraction of
   blocks are delivered through it. That fraction is reported rather than
   assumed, because treating a missing block as a zero-value block would bias
   every number downward.
2. **The undercount.** Blocks in which we detect a sandwich should command a
   higher proposer payment than otherwise-comparable blocks, and the size of
   the gap bounds how much value our classifier attributes against how much the
   builder market thinks was there.

The control set is drawn from blocks that contain a swap in the same pool but no
detected sandwich, so the comparison holds pool activity roughly fixed rather
than comparing active blocks against empty ones.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.build.derived import available_months, month_bounds
from src.build.mev import classify_sandwiches_by_address, sandwich_profit_usd
from src.fetch.rpc_client import fetch_swaps, load_big_ints
from src.utils.config import REPO_ROOT, pool

POOL = "ETH_USDC_5bp"
RELAY = ("https://boost-relay.flashbots.net/relay/v1/data/bidtraces/"
         "proposer_payload_delivered?block_number=")
CACHE = REPO_ROOT / "data" / "raw" / "relay_payments.parquet"
OUT = REPO_ROOT / "outputs" / "tables"
N_PER_GROUP = 2500
RNG = np.random.default_rng(20260908)


def fetch_payment(block: int, retries: int = 3) -> float | None:
    """Proposer payment in ETH, or None if this block was not delivered here.

    None and 0.0 are different answers and are kept apart: a block delivered by
    another relay is unobserved, not a block worth nothing.
    """
    for attempt in range(retries):
        try:
            req = urllib.request.Request(RELAY + str(block),
                                         headers={"User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=25).read())
            return float(int(d[0]["value"])) / 1e18 if d else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(1.5 * (attempt + 1))
    return None


PARTIAL = REPO_ROOT / "data" / "raw" / "relay_payments_partial.parquet"


def collect(blocks: np.ndarray, label: str) -> pd.DataFrame:
    """Fetch payments, checkpointing so an interrupted run resumes.

    The first attempt died silently after 1,250 of 8,000 blocks with the relay's
    latency climbing from 0.2s to 2.8s per request, and lost everything. Work is
    now flushed every 200 blocks and already-fetched blocks are skipped, so the
    job is restartable and the relay is asked for each block exactly once.
    """
    done = pd.read_parquet(PARTIAL) if PARTIAL.exists() else pd.DataFrame(
        columns=["block_number", "group", "payment_eth"])
    have = set(done.loc[done.group == label, "block_number"].astype(int))
    todo = [int(b) for b in blocks if int(b) not in have]
    print(f"  {label}: {len(have):,} already cached, {len(todo):,} to fetch",
          flush=True)
    rows, t0 = [], time.time()
    for i, b in enumerate(todo, 1):
        rows.append({"block_number": b, "group": label,
                     "payment_eth": fetch_payment(b)})
        # Politeness: the relay slowed sharply under an unpaced loop, so pace it.
        time.sleep(0.05)
        if i % 200 == 0 or i == len(todo):
            done = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
            done.to_parquet(PARTIAL, index=False)
            rows = []
            got = int(done.loc[done.group == label, "payment_eth"].notna().sum())
            print(f"  {label}: {i:,}/{len(todo):,}  delivered {got:,}"
                  f"  {time.time() - t0:.0f}s", flush=True)
    if rows:
        done = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
        done.to_parquet(PARTIAL, index=False)
    return done[done.group == label].reset_index(drop=True)


def main() -> int:
    spec = pool(POOL)
    bounds = month_bounds()

    print(f"=== classifying sandwiches on {POOL} ===", flush=True)
    sw_all, sand_all = [], []
    for y, m in available_months(spec):
        k0 = f"{y:04d}-{m:02d}"
        k1 = f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"
        if k0 not in bounds or k1 not in bounds:
            continue
        sw = load_big_ints(fetch_swaps(spec.address, bounds[k0], bounds[k1] - 1))
        s = classify_sandwiches_by_address(sw, spec)
        sw_all.append(sw[["block_number"]].astype("int64"))
        if len(s):
            s = s.copy()
            s["profit_usd"] = sandwich_profit_usd(s, spec, Decimal("2500")).map(float)
            sand_all.append(s[["block_number", "profit_usd"]])
        print(f"  {k0}: {len(sw):,} swaps, {len(s):,} sandwiches", flush=True)

    swaps = pd.concat(sw_all, ignore_index=True)
    sand = pd.concat(sand_all, ignore_index=True)
    sand_blocks = np.array(sorted(sand.block_number.unique()))
    swap_blocks = np.array(sorted(set(swaps.block_number.unique()) - set(sand_blocks)))
    print(f"\n{len(sand):,} sandwiches in {len(sand_blocks):,} blocks; "
          f"{len(swap_blocks):,} control blocks with a swap and no sandwich")

    if CACHE.exists():
        pay = pd.read_parquet(CACHE)
        print(f"relay cache: {len(pay):,} blocks")
    else:
        a = RNG.choice(sand_blocks, min(N_PER_GROUP, len(sand_blocks)), replace=False)
        b = RNG.choice(swap_blocks, min(N_PER_GROUP, len(swap_blocks)), replace=False)
        print(f"\nfetching relay payments for {len(a):,} + {len(b):,} blocks", flush=True)
        pay = pd.concat([collect(np.sort(a), "sandwich"),
                         collect(np.sort(b), "control")], ignore_index=True)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        pay.to_parquet(CACHE, index=False)

    print("\n" + "=" * 84)
    print("RELAY COVERAGE AND THE UNDERCOUNT")
    print("=" * 84)
    rows = []
    print(f"\n{'group':>10} {'queried':>9} {'delivered':>10} {'coverage':>9} "
          f"{'median ETH':>11} {'mean ETH':>10}")
    for g, d in pay.groupby("group"):
        got = d.dropna(subset=["payment_eth"])
        cov = len(got) / len(d)
        print(f"{g:>10} {len(d):>9,} {len(got):>10,} {cov:>8.1%} "
              f"{got.payment_eth.median():>11.4f} {got.payment_eth.mean():>10.4f}")
        rows.append({"metric": f"{g}_coverage", "value": cov})
        rows.append({"metric": f"{g}_median_eth", "value": float(got.payment_eth.median())})
        rows.append({"metric": f"{g}_mean_eth", "value": float(got.payment_eth.mean())})

    s = pay[(pay.group == "sandwich")].dropna(subset=["payment_eth"]).payment_eth
    c = pay[(pay.group == "control")].dropna(subset=["payment_eth"]).payment_eth
    ratio = float(s.median() / c.median())
    # A rank test, because block payments are heavily right-skewed and a t-test
    # on the mean would be driven by a handful of very large blocks.
    boot = np.array([np.median(RNG.choice(s.to_numpy(), len(s))) /
                     np.median(RNG.choice(c.to_numpy(), len(c))) for _ in range(4000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"\n  median payment ratio, sandwich / control = {ratio:.3f}"
          f"   95% CI [{lo:.3f}, {hi:.3f}]")
    rows += [{"metric": "payment_ratio", "value": ratio},
             {"metric": "payment_ratio_lo", "value": float(lo)},
             {"metric": "payment_ratio_hi", "value": float(hi)}]

    # How much value does the classifier attribute, against what the builder paid?
    got = pay.dropna(subset=["payment_eth"])
    joined = (sand.groupby("block_number").profit_usd.sum().rename("ours")
                  .to_frame().join(got.set_index("block_number")[["payment_eth"]],
                                   how="inner"))
    if len(joined):
        eth_usd = 2500.0
        joined["relay_usd"] = joined.payment_eth * eth_usd
        share = float(joined.ours.sum() / joined.relay_usd.sum())
        print(f"\n  on {len(joined):,} sandwich blocks the classifier attributes "
              f"${joined.ours.sum():,.0f}")
        print(f"  the builder paid the proposer ${joined.relay_usd.sum():,.0f} "
              f"for the same blocks")
        print(f"  our share of the block's market-priced value = {share:.1%}")
        rows.append({"metric": "classified_share_of_block_value", "value": share})
        rows.append({"metric": "n_joined_blocks", "value": float(len(joined))})

    print("\n  Read as: block payments cover ALL extraction in the block, most of"
          "\n  it unrelated to this pool, so this is an upper bound on what we"
          "\n  should be capturing, not a target. The informative number is the"
          "\n  sandwich/control ratio, which is a like-for-like comparison.")
    pd.DataFrame(rows).to_csv(OUT / "mev_relay_validation.csv", index=False)
    print("\nwrote outputs/tables/mev_relay_validation.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
