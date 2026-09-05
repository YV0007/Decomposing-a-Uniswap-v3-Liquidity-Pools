"""Ethereum JSON-RPC archive client — the primary on-chain data source.

Substituted for Dune Analytics; see DECISIONS.md "Data source substitution".
Raw `eth_getLogs` is a strictly better source for this project than a SQL
warehouse: event fields arrive as canonical hex integers with no intermediary
decoding, `logIndex` gives the exact within-block ordering that MEV
classification needs, and the same query can be replayed against several
independent providers as a cross-check.

Precision contract
------------------
Every on-chain integer is carried as a Python ``int`` and persisted as a
**string**. This is not fussiness: ``sqrtPriceX96`` is a uint160 (up to ~1.5e48)
and ``liquidity`` is a uint128, both far beyond the int64 that parquet and
numpy would silently coerce them into. `amount0`/`amount1` are int256. A float
anywhere in this path is the failure mode that "matches on day 1 and breaks at
scale".
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

#: Public archive endpoints, in preference order. Tenderly's public gateway
#: serves 50k-block spans; the others are failover and cross-check.
DEFAULT_ENDPOINTS = [
    "https://gateway.tenderly.co/public/mainnet",
    "https://docs-demo.quiknode.pro",
    "https://rpc.mevblocker.io",
]

#: keccak256("Swap(address,address,int256,int256,uint160,uint128,int24)")
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
#: keccak256("Mint(address,address,int24,int24,uint128,uint256,uint256)")
MINT_TOPIC = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
#: keccak256("Burn(address,int24,int24,uint128,uint256,uint256)")
BURN_TOPIC = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"

#: Columns persisted as decimal strings to survive parquet without precision loss.
BIG_INT_COLUMNS = ["amount0", "amount1", "sqrt_price_x96", "liquidity"]


class RPCError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Low-level client
# --------------------------------------------------------------------------- #

@dataclass
class RPCClient:
    """JSON-RPC client with endpoint failover and polite backoff."""

    endpoints: list[str] = None
    timeout: int = 60
    max_retries: int = 4
    sleep_between: float = 0.15

    def __post_init__(self) -> None:
        if self.endpoints is None:
            self.endpoints = list(DEFAULT_ENDPOINTS)
        self._cursor = 0

    def _post(self, url: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def call(self, method: str, params: list, endpoint: str | None = None):
        """One RPC call, rotating endpoints on failure.

        Rate limits (429) and provider routing errors are retried on the next
        endpoint rather than failed, since the three providers have different
        limits and any of them can answer.
        """
        errors: list[str] = []
        urls = [endpoint] if endpoint else self.endpoints
        for attempt in range(self.max_retries):
            url = urls[self._cursor % len(urls)] if not endpoint else endpoint
            try:
                out = self._post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if "result" in out:
                    time.sleep(self.sleep_between)
                    return out["result"]
                errors.append(f"{url}: {out.get('error')}")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                errors.append(f"{url}: {type(exc).__name__} {exc}")
            self._cursor += 1
            time.sleep(0.5 * (2**attempt))
        raise RPCError(f"{method} failed on all endpoints:\n  " + "\n  ".join(errors))

    # -- convenience wrappers ------------------------------------------------ #

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_block(self, number: int, full: bool = False) -> dict:
        return self.call("eth_getBlockByNumber", [hex(number), full])

    def block_timestamp(self, number: int) -> int:
        return int(self.get_block(number)["timestamp"], 16)

    def eth_call(self, to: str, data: str, block: str | int = "latest") -> str:
        tag = block if isinstance(block, str) else hex(block)
        return self.call("eth_call", [{"to": to, "data": data}, tag])

    def get_logs(self, address: str, topics: list, from_block: int, to_block: int) -> list[dict]:
        return self.call(
            "eth_getLogs",
            [{"address": address, "topics": topics,
              "fromBlock": hex(from_block), "toBlock": hex(to_block)}],
        )


# --------------------------------------------------------------------------- #
# Decoding — exact integers only
# --------------------------------------------------------------------------- #

def _to_signed(value: int, bits: int) -> int:
    """Two's-complement reinterpretation of a `bits`-wide value."""
    if value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


def _decode_signed_word(word: int, declared_bits: int) -> int:
    """Decode an ABI-encoded signed integer from its 32-byte word.

    The ABI **sign-extends** signed integers to the full word, so an ``int24``
    of -2 arrives as ``0xffff...fffe`` — 256 bits of ones — not as a 24-bit
    ``0xfffffe``. Reinterpreting that word at its declared width yields a
    78-digit positive number instead of -2.

    So the decode is always at 256 bits, with the declared width used only to
    range-check the result afterwards.

    This is not hypothetical. Ticks on ETH/USDC sit near +205,000 and decode
    identically under either reading, so the error is invisible there. On
    USDC/USDT, which trades at a price near 1, every tick is near zero and
    routinely negative — and every swap decodes to garbage. It surfaced only
    because parquet refused to store the oversized integer; in memory, or via
    CSV, it would have passed silently into the price cross-check.
    """
    value = _to_signed(word, 256)
    lo, hi = -(1 << (declared_bits - 1)), (1 << (declared_bits - 1)) - 1
    if not lo <= value <= hi:
        raise ValueError(
            f"decoded {value} does not fit int{declared_bits} [{lo}, {hi}]; "
            f"the ABI word was 0x{word:064x}"
        )
    return value


def _words(data_hex: str) -> list[int]:
    """Split ABI-encoded data into 32-byte words as unsigned ints."""
    raw = data_hex[2:] if data_hex.startswith("0x") else data_hex
    if len(raw) % 64:
        raise ValueError(f"data is not a whole number of words: {len(raw)} chars")
    return [int(raw[i : i + 64], 16) for i in range(0, len(raw), 64)]


def decode_swap_log(log: dict) -> dict:
    """Decode one v3 `Swap` event.

    Non-indexed payload, in order: ``amount0`` (int256), ``amount1`` (int256),
    ``sqrtPriceX96`` (uint160), ``liquidity`` (uint128), ``tick`` (int24).
    ``sender`` and ``recipient`` are indexed and arrive in the topics.

    Sign convention: amounts are from the **pool's** perspective. A positive
    ``amount0`` means token0 flowed into the pool.
    """
    w = _words(log["data"])
    if len(w) != 5:
        raise ValueError(f"expected 5 data words in a Swap log, got {len(w)}")
    return {
        "block_number": int(log["blockNumber"], 16),
        # Both archive providers return blockTimestamp on the log itself, which
        # removes an entire second pass of ~10k eth_getBlockByNumber calls per
        # pool-month. Absent on some providers, hence the sentinel.
        "block_timestamp": int(log["blockTimestamp"], 16) if "blockTimestamp" in log else -1,
        "log_index": int(log["logIndex"], 16),
        "tx_hash": log["transactionHash"],
        "tx_index": int(log["transactionIndex"], 16),
        "sender": "0x" + log["topics"][1][-40:],
        "recipient": "0x" + log["topics"][2][-40:],
        "amount0": _decode_signed_word(w[0], 256),
        "amount1": _decode_signed_word(w[1], 256),
        "sqrt_price_x96": w[2],
        "liquidity": w[3],
        "tick": _decode_signed_word(w[4], 24),
    }


# --------------------------------------------------------------------------- #
# Block <-> timestamp
# --------------------------------------------------------------------------- #

def block_at_or_before(client: RPCClient, target_ts: int, lo: int = 15_000_000, hi: int | None = None) -> int:
    """Highest block whose timestamp is <= `target_ts`, by binary search.

    "At or before" matters: the sample boundary must not reach forward past the
    requested instant, for the same reason the CEX alignment rule does not.
    """
    if hi is None:
        hi = client.block_number()
    if client.block_timestamp(lo) > target_ts:
        raise ValueError(f"target {target_ts} precedes lower bound block {lo}")
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if client.block_timestamp(mid) <= target_ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def fetch_logs_chunked(
    client: RPCClient, address: str, topic: str, from_block: int, to_block: int,
    chunk: int = 50_000, verbose: bool = True,
) -> list[dict]:
    """Page through a block range, halving the chunk on a provider range error."""
    out: list[dict] = []
    start = from_block
    span = chunk
    while start <= to_block:
        end = min(start + span - 1, to_block)
        try:
            logs = client.get_logs(address, [topic], start, end)
        except RPCError:
            if span <= 500:
                raise
            span //= 2
            continue
        out.extend(logs)
        if verbose:
            pct = 100 * (end - from_block + 1) / max(1, to_block - from_block + 1)
            print(f"  blocks {start}-{end}  +{len(logs):5d} logs  (total {len(out):7d})  {pct:5.1f}%", flush=True)
        start = end + 1
    return out


def swaps_to_frame(logs: list[dict]) -> pd.DataFrame:
    """Decode swap logs into a frame with big integers held as strings.

    Sorted by ``(block_number, log_index)`` — the canonical on-chain ordering,
    and the ordering MEV classification depends on.
    """
    rows = [decode_swap_log(lg) for lg in logs]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["block_number", "log_index"]).reset_index(drop=True)
    if (df["block_timestamp"] < 0).any():
        raise RPCError(
            "some logs lack blockTimestamp; this provider requires the separate "
            "eth_getBlockByNumber pass. Switch endpoint or fetch timestamps."
        )
    for col in BIG_INT_COLUMNS:
        df[col] = df[col].map(str)          # never int64, never float64
    return df


def load_big_ints(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Inverse of the string persistence: back to Python ``int`` objects.

    Dtype is forced to ``object`` rather than left to pandas' inference. This is
    not cosmetic. Inference is *data-dependent*: a column of WETH amounts lands
    in ``object`` only if the sample happens to contain a swap above the int64
    ceiling of 9.22 WETH, and in ``int64`` otherwise. A quiet month would
    silently produce a fixed-width column that overflows the moment a large
    swap arrives, or when two months are concatenated — the failure mode that
    matches on day 1 and breaks at scale. Forcing ``object`` makes the
    representation independent of the data it happens to hold.
    """
    df = df.copy()
    for col in (columns or BIG_INT_COLUMNS):
        if col in df.columns:
            df[col] = pd.Series(
                [int(v) for v in df[col]], index=df.index, dtype=object
            )
    return df


def assert_exact_integer_columns(df: pd.DataFrame, columns: list[str] | None = None) -> None:
    """Raise unless every precision-critical column holds Python ints.

    Called after any load or transform that could have coerced them. A float
    here is a silent ~1e-8 relative error in the price path; a fixed-width int
    is a latent overflow.
    """
    for col in (columns or BIG_INT_COLUMNS):
        if col not in df.columns:
            continue
        if df[col].dtype != object:
            raise TypeError(
                f"column {col!r} has dtype {df[col].dtype}, expected object holding "
                f"Python ints. Fixed-width or floating dtypes lose exactness on "
                f"uint160/uint128/int256 fields."
            )
        bad = next((v for v in df[col] if not isinstance(v, int) or isinstance(v, bool)), None)
        if bad is not None:
            raise TypeError(f"column {col!r} contains a {type(bad).__name__}: {bad!r}")


def fetch_swaps(
    pool_address: str, from_block: int, to_block: int,
    cache_dir: Path | None = None, client: RPCClient | None = None, force: bool = False,
) -> pd.DataFrame:
    """Swaps for one pool over a block range, cached to parquet."""
    from src.utils.config import REPO_ROOT

    client = client or RPCClient()
    cache_dir = cache_dir or REPO_ROOT / "data" / "raw" / "swaps"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # v3: fixes int24 tick sign-extension (see _decode_signed_word). Earlier
    # caches may hold garbage ticks for any pool trading near price 1, so they
    # are not interchangeable.
    cache = cache_dir / f"{pool_address.lower()}_{from_block}_{to_block}_v3.parquet"

    if cache.exists() and not force:
        print(f"  cache hit: {cache.name}")
        return pd.read_parquet(cache)

    print(f"fetching swaps {pool_address} blocks {from_block}-{to_block}")
    logs = fetch_logs_chunked(client, pool_address, SWAP_TOPIC, from_block, to_block)
    df = swaps_to_frame(logs)
    df.to_parquet(cache, index=False)
    print(f"  wrote {len(df)} swaps -> {cache.name}")
    return df


# --------------------------------------------------------------------------- #
# Pool metadata — the Stage 1.1 verification
# --------------------------------------------------------------------------- #

SELECTORS = {
    "token0": "0x0dfe1681",
    "token1": "0xd21220a7",
    "fee": "0xddca3f43",
    "tickSpacing": "0xd0c93a7c",
    "liquidity": "0x1a686502",
    "decimals": "0x313ce567",
    "symbol": "0x95d89b41",
}


def read_pool_metadata(pool_address: str, client: RPCClient | None = None) -> dict:
    """Read token order, fee and tick spacing straight from the pool contract.

    This is the Stage 1.1 verification, done against the chain itself rather
    than against a block explorer's rendering of it. token0/token1 are
    address-sorted, not semantic — the single most common cause of an inverted
    price, and the reason this is a hard gate rather than an assumption.
    """
    client = client or RPCClient()
    md: dict = {"address": pool_address.lower()}
    md["token0"] = "0x" + client.eth_call(pool_address, SELECTORS["token0"])[-40:]
    md["token1"] = "0x" + client.eth_call(pool_address, SELECTORS["token1"])[-40:]
    md["fee"] = int(client.eth_call(pool_address, SELECTORS["fee"]), 16)
    md["tick_spacing"] = int(client.eth_call(pool_address, SELECTORS["tickSpacing"]), 16)
    for side in ("token0", "token1"):
        md[f"{side}_decimals"] = int(client.eth_call(md[side], SELECTORS["decimals"]), 16)
    return md
