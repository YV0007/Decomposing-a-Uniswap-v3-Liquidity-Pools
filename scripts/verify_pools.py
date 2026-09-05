"""Stage 1.1 — verify every configured pool against the chain.

token0/token1 are address-sorted, not semantic. Decimals differ per token
(USDC 6, WETH 18, WBTC 8). Either being wrong inverts or rescales every price
downstream, silently. This script is the gate; `config.yaml`'s
`verified_on_etherscan` flag must not be set by hand without it passing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetch.rpc_client import RPCClient, read_pool_metadata
from src.utils.config import pools

TOKEN_NAMES = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
}

STABLES = {"USDC", "USDT", "DAI"}


def expected_invert(token0_symbol: str, token1_symbol: str) -> bool | None:
    """Should the raw price be inverted to quote the risky asset in the stable?

    Raw price is token1-per-token0. We want stable-per-risky, so invert exactly
    when token0 is the stable and token1 is the risky asset. For a
    stable-stable pair the orientation is arbitrary (the price is ~1 either
    way), so the check abstains rather than asserting a convention.
    """
    t0_stable, t1_stable = token0_symbol in STABLES, token1_symbol in STABLES
    if t0_stable and t1_stable:
        return None          # stable/stable — orientation is a free choice
    if t0_stable and not t1_stable:
        return True
    return False


def main() -> int:
    client = RPCClient()
    all_ok = True
    print(f"{'pool':<18} {'check':<16} {'config':<46} {'on-chain':<46} ok")
    print("-" * 136)
    for spec in pools("all"):
        md = read_pool_metadata(spec.address, client)
        checks = [
            ("token0", spec.token0.address.lower(), md["token0"]),
            ("token1", spec.token1.address.lower(), md["token1"]),
            ("fee", str(spec.fee_tier_bps * 100), str(md["fee"])),
            ("tick_spacing", str(spec.tick_spacing), str(md["tick_spacing"])),
            ("token0_decimals", str(spec.token0.decimals), str(md["token0_decimals"])),
            ("token1_decimals", str(spec.token1.decimals), str(md["token1_decimals"])),
        ]
        for name, want, got in checks:
            ok = want == got
            all_ok &= ok
            print(f"{spec.id:<18} {name:<16} {want:<46} {got:<46} {'OK' if ok else 'MISMATCH'}")
        t0 = TOKEN_NAMES.get(md["token0"], "?")
        t1 = TOKEN_NAMES.get(md["token1"], "?")
        should_invert = expected_invert(t0, t1)
        if should_invert is None:
            note = f"{t0}/{t1} both stable -> free choice"
            verdict = "N/A"
        else:
            note = f"token0={t0}, token1={t1} -> {should_invert}"
            verdict = "OK" if should_invert == spec.invert_price else "MISMATCH"
            all_ok &= should_invert == spec.invert_price
        print(f"{spec.id:<18} {'invert_price':<16} {str(spec.invert_price):<46} "
              f"{note:<46} {verdict}")
        print()
    print("GATE:", "PASS — safe to set verified_on_etherscan: true" if all_ok else "FAIL — do not proceed")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
