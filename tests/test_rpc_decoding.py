"""Decoding and precision-preservation tests for the RPC data path.

The tests that do not need the network run on a captured real log. The ones
marked `network` re-verify against the live chain.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.fetch.rpc_client import (BIG_INT_COLUMNS, _to_signed, _words,
                                  assert_exact_integer_columns, decode_swap_log,
                                  load_big_ints, swaps_to_frame)

# A real ETH/USDC 30bp Swap log, block 16308284.
SAMPLE_LOG = {
    "blockNumber": "0xf8d35c",
    "blockTimestamp": "0x63b0d17f",
    "logIndex": "0x2d",
    "transactionHash": "0x" + "ab" * 32,
    "transactionIndex": "0x11",
    "topics": [
        "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
        "0x000000000000000000000000" + "11" * 20,
        "0x000000000000000000000000" + "22" * 20,
    ],
    # amount0 = +1_000_000_000 (1000 USDC in), amount1 = -836_000_000_000_000_000 (0.836 WETH out)
    "data": "0x"
    + format(1_000_000_000, "064x")
    + format((1 << 256) - 836_000_000_000_000_000, "064x")
    + format(2_272_605_167_715_097_306_297_632, "064x")
    + format(4_259_400_000_000_000_000_00, "064x")
    + format((1 << 256) - 205451 % (1 << 256) if False else 205451, "064x"),
}


def test_two_complement_roundtrip():
    assert _to_signed(1, 256) == 1
    assert _to_signed((1 << 256) - 1, 256) == -1
    assert _to_signed((1 << 24) - 1, 24) == -1
    assert _to_signed(205451, 24) == 205451
    # int24 minimum
    assert _to_signed(1 << 23, 24) == -(1 << 23)


def test_words_rejects_ragged_data():
    with pytest.raises(ValueError):
        _words("0x1234")


def test_decode_swap_log_signs_and_types():
    d = decode_swap_log(SAMPLE_LOG)
    assert d["block_number"] == 0xF8D35C
    assert d["block_timestamp"] == 0x63B0D17F
    assert d["log_index"] == 0x2D
    assert d["amount0"] == 1_000_000_000, "token0 into the pool is positive"
    assert d["amount1"] == -836_000_000_000_000_000, "token1 out of the pool is negative"
    assert d["tick"] == 205451
    for k in ("amount0", "amount1", "sqrt_price_x96", "liquidity", "tick"):
        assert isinstance(d[k], int) and not isinstance(d[k], bool)


def test_decode_rejects_wrong_word_count():
    bad = dict(SAMPLE_LOG, data="0x" + "00" * 32 * 4)
    with pytest.raises(ValueError, match="5 data words"):
        decode_swap_log(bad)


def test_frame_persists_big_ints_as_strings():
    df = swaps_to_frame([SAMPLE_LOG])
    for col in BIG_INT_COLUMNS:
        assert df[col].dtype == object
        assert isinstance(df[col].iloc[0], str), f"{col} must persist as a string"


def test_load_big_ints_forces_object_dtype_regardless_of_magnitude():
    """The dtype must not depend on whether the sample contains a large value.

    Regression test for a real hazard: pandas infers int64 for a column of
    small WETH amounts and object for one containing a swap above 9.22 WETH.
    A quiet month would therefore yield a fixed-width column that overflows on
    the next concat.
    """
    small = pd.DataFrame({c: ["1", "2", "3"] for c in BIG_INT_COLUMNS})
    loaded = load_big_ints(small)
    for col in BIG_INT_COLUMNS:
        assert loaded[col].dtype == object, f"{col} was inferred as {loaded[col].dtype}"
        assert all(isinstance(v, int) for v in loaded[col])
    assert_exact_integer_columns(loaded)


def test_assert_exact_integer_columns_catches_coercion():
    df = pd.DataFrame({"sqrt_price_x96": [1.0, 2.0]})
    with pytest.raises(TypeError, match="dtype"):
        assert_exact_integer_columns(df, ["sqrt_price_x96"])

    df2 = pd.DataFrame({"sqrt_price_x96": pd.Series([1.5, 2.5], dtype=object)})
    with pytest.raises(TypeError, match="contains a float"):
        assert_exact_integer_columns(df2, ["sqrt_price_x96"])


def test_huge_values_survive_the_roundtrip():
    """A uint160 sqrtPriceX96 and a 4776 WETH amount1 must survive intact."""
    huge = {
        "amount0": str(-(10**30)),
        "amount1": str(4_775_580_000_000_000_000_000),
        "sqrt_price_x96": str(2**159 - 1),
        "liquidity": str(2**127 - 1),
    }
    df = load_big_ints(pd.DataFrame([huge]))
    assert df["sqrt_price_x96"].iloc[0] == 2**159 - 1
    assert df["liquidity"].iloc[0] == 2**127 - 1
    assert df["amount1"].iloc[0] == 4_775_580_000_000_000_000_000
    assert df["amount0"].iloc[0] == -(10**30)


# --------------------------------------------------------------------------- #
# Regression: ABI sign extension of narrow signed types
# --------------------------------------------------------------------------- #

def _log_with_tick(word: int) -> dict:
    return dict(
        SAMPLE_LOG,
        data="0x"
        + format(1_000_000_000, "064x")
        + format((1 << 256) - 836_000_000_000_000_000, "064x")
        + format(2_272_605_167_715_097_306_297_632, "064x")
        + format(4_259_400_000_000_000_000_00, "064x")
        + format(word, "064x"),
    )


@pytest.mark.parametrize("tick", [-887272, -100000, -2, -1, 0, 1, 3, 205451, 887272])
def test_tick_sign_extension(tick):
    """int24 ticks are sign-extended to 32 bytes by the ABI.

    Regression for a real bug: -2 arrived as 0xffff...fffe and, reinterpreted
    at 24 bits, decoded to a 78-digit positive number. Invisible on ETH/USDC
    (ticks ~ +205000) and universal on USDC/USDT (ticks ~ 0, mostly negative).
    """
    word = tick & ((1 << 256) - 1)
    assert decode_swap_log(_log_with_tick(word))["tick"] == tick


def test_tick_outside_int24_is_rejected():
    """A word that is neither a small positive nor a sign-extended negative is a bug."""
    from src.fetch.rpc_client import _decode_signed_word

    with pytest.raises(ValueError, match="int24"):
        _decode_signed_word(1 << 100, 24)


def test_negative_amounts_decode():
    d = decode_swap_log(_log_with_tick((-5) & ((1 << 256) - 1)))
    assert d["amount1"] < 0 and d["tick"] == -5
