"""Exact arithmetic for Uniswap v3 price and liquidity maths.

This module exists because `sqrtPriceX96` is a uint160 and does not survive
float64. A silent relative error of ~1e-8 in the price path compounds through
the LVR sum into a number that looks plausible and is wrong. Every conversion
between `sqrtPriceX96`, ticks and human-readable prices goes through here.

Conventions
-----------
*Raw price* is the pool's native quantity: token1 base units per token0 base
unit, i.e. ``(sqrtPriceX96 / 2**96) ** 2``. It is monotone increasing in tick.

*Human price* applies the decimal adjustment ``10 ** (decimals0 - decimals1)``
and, when ``invert=True``, takes the reciprocal. For the ETH/USDC pools token0
is USDC and token1 is WETH, so the raw price is WETH-per-USDC and ``invert``
must be set to obtain USD per ETH.

All public functions accept and return :class:`~decimal.Decimal` or :class:`int`.
Passing a ``float`` raises :class:`PrecisionError` rather than silently
degrading. Convert to ``float`` only at the plotting boundary.
"""

from __future__ import annotations

from decimal import Decimal, getcontext, localcontext, ROUND_FLOOR

__all__ = [
    "PrecisionError",
    "Q96",
    "MIN_TICK",
    "MAX_TICK",
    "TICK_BASE",
    "TICK_SNAP_REL",
    "PRECISION",
    "reject_float",
    "raw_price_from_sqrt_price_x96",
    "sqrt_price_x96_from_raw_price",
    "to_human_price",
    "to_raw_price",
    "sqrt_price_x96_to_price",
    "price_to_sqrt_price_x96",
    "tick_to_raw_price",
    "tick_to_price",
    "price_to_tick",
    "get_sqrt_ratio_at_tick",
    "get_tick_at_sqrt_ratio",
    "amount0_for_liquidity",
    "amount1_for_liquidity",
    "position_amounts",
]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

Q96: int = 1 << 96
Q128: int = 1 << 128
MIN_TICK: int = -887272
MAX_TICK: int = 887272
TICK_BASE: Decimal = Decimal("1.0001")

#: Working precision. The tick range spans ~1e38 to ~1e-39 in raw price, so the
#: context must carry the full dynamic range plus working digits.
PRECISION: int = 78

#: Relative tolerance for snapping a price onto a tick boundary.
#: ``tick_to_price`` can land one ulp below the exact boundary (~1e-78
#: relative), which a naive floor would push down a whole tick. One tick is
#: 1e-4 in relative price, so this snap sits 26 orders of magnitude clear of
#: any economically real price difference and 48 above the rounding it fixes.
TICK_SNAP_REL: Decimal = Decimal("1e-30")

getcontext().prec = PRECISION


class PrecisionError(TypeError):
    """Raised when a float enters a code path that must stay exact."""


def reject_float(value: object, name: str = "value") -> None:
    """Raise if ``value`` is a float.

    Called at every public entry point. ``bool`` is an ``int`` subclass and is
    also rejected, since a boolean price is always a bug.
    """
    if isinstance(value, float):
        raise PrecisionError(
            f"{name} is a float ({value!r}); sqrtPriceX96 arithmetic must use "
            f"int or Decimal. Convert to float only at the plotting boundary."
        )
    if isinstance(value, bool):
        raise PrecisionError(f"{name} is a bool ({value!r}); expected int or Decimal.")


def _as_decimal(value: int | Decimal, name: str) -> Decimal:
    reject_float(value, name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise PrecisionError(f"{name} has type {type(value).__name__}; expected int or Decimal.")


# --------------------------------------------------------------------------- #
# sqrtPriceX96  <->  price
# --------------------------------------------------------------------------- #

def raw_price_from_sqrt_price_x96(sqrt_price_x96: int) -> Decimal:
    """Raw pool price (token1 base units per token0 base unit).

    ``price_raw = (sqrtPriceX96 / 2**96) ** 2``, evaluated with the numerator
    squared as an exact integer before the single division.
    """
    reject_float(sqrt_price_x96, "sqrt_price_x96")
    if not isinstance(sqrt_price_x96, int):
        raise PrecisionError("sqrt_price_x96 must be int (uint160 from the chain).")
    if sqrt_price_x96 <= 0:
        raise ValueError(f"sqrt_price_x96 must be positive, got {sqrt_price_x96}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        # Square in exact integer arithmetic; divide exactly once.
        return Decimal(sqrt_price_x96 * sqrt_price_x96) / Decimal(Q96 * Q96)


def sqrt_price_x96_from_raw_price(raw_price: Decimal) -> int:
    """Inverse of :func:`raw_price_from_sqrt_price_x96`, floored to uint160."""
    p = _as_decimal(raw_price, "raw_price")
    if p <= 0:
        raise ValueError(f"raw_price must be positive, got {p}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return int((p.sqrt() * Decimal(Q96)).to_integral_value(rounding=ROUND_FLOOR))


def to_human_price(
    raw_price: Decimal, decimals0: int, decimals1: int, invert: bool = False
) -> Decimal:
    """Apply the decimal adjustment and optional inversion.

    ``human = raw * 10 ** (decimals0 - decimals1)``, then reciprocal if
    ``invert``. The decimal adjustment is not optional: USDC has 6 and WETH 18,
    so omitting it puts the price out by 10**12.
    """
    p = _as_decimal(raw_price, "raw_price")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        human = p * (Decimal(10) ** (decimals0 - decimals1))
        return (Decimal(1) / human) if invert else human


def to_raw_price(
    human_price: Decimal, decimals0: int, decimals1: int, invert: bool = False
) -> Decimal:
    """Inverse of :func:`to_human_price`."""
    p = _as_decimal(human_price, "human_price")
    if p <= 0:
        raise ValueError(f"human_price must be positive, got {p}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        base = (Decimal(1) / p) if invert else p
        return base * (Decimal(10) ** (decimals1 - decimals0))


def sqrt_price_x96_to_price(
    sqrt_price_x96: int, decimals0: int, decimals1: int, invert: bool = False
) -> Decimal:
    """`sqrtPriceX96` straight to a human-readable price. The common entry point."""
    return to_human_price(
        raw_price_from_sqrt_price_x96(sqrt_price_x96), decimals0, decimals1, invert
    )


def price_to_sqrt_price_x96(
    human_price: Decimal, decimals0: int, decimals1: int, invert: bool = False
) -> int:
    """Human-readable price straight to `sqrtPriceX96`."""
    return sqrt_price_x96_from_raw_price(
        to_raw_price(human_price, decimals0, decimals1, invert)
    )


# --------------------------------------------------------------------------- #
# Ticks
# --------------------------------------------------------------------------- #

def tick_to_raw_price(tick: int) -> Decimal:
    """``P_raw = 1.0001 ** tick``, by definition of the tick.

    Ticks are integers, prices are not. The round trip
    ``price_to_tick(tick_to_price(t)) == t`` must be exact — see
    ``tests/test_precision.py``.
    """
    reject_float(tick, "tick")
    if not isinstance(tick, int):
        raise PrecisionError("tick must be an int.")
    if not MIN_TICK <= tick <= MAX_TICK:
        raise ValueError(f"tick {tick} outside [{MIN_TICK}, {MAX_TICK}]")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return TICK_BASE ** tick


def tick_to_price(
    tick: int, decimals0: int, decimals1: int, invert: bool = False
) -> Decimal:
    """Tick to human-readable price."""
    return to_human_price(tick_to_raw_price(tick), decimals0, decimals1, invert)


def _raw_price_to_tick(raw_price: Decimal) -> int:
    """Greatest tick whose raw price is <= ``raw_price``.

    Seeded by logarithm, then corrected by exact Decimal comparison so the
    result never depends on the precision of the log.
    """
    p = _as_decimal(raw_price, "raw_price")
    if p <= 0:
        raise ValueError(f"raw_price must be positive, got {p}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        seed = int((p.ln() / TICK_BASE.ln()).to_integral_value(rounding=ROUND_FLOOR))
        seed = max(MIN_TICK, min(MAX_TICK, seed))
        # Correct at most a couple of steps in either direction.
        while seed > MIN_TICK and TICK_BASE ** seed > p:
            seed -= 1
        while seed < MAX_TICK and TICK_BASE ** (seed + 1) <= p:
            seed += 1
        # Snap onto the boundary above when p is indistinguishably below it.
        if seed < MAX_TICK:
            nxt = TICK_BASE ** (seed + 1)
            if (nxt - p) / nxt < TICK_SNAP_REL:
                seed += 1
        return seed


def price_to_tick(
    human_price: Decimal, decimals0: int, decimals1: int, invert: bool = False
) -> int:
    """Human-readable price to the greatest tick at or below it *in raw space*.

    Flooring is defined in raw price, which is monotone increasing in tick,
    so the semantics do not flip when ``invert`` is set.
    """
    return _raw_price_to_tick(to_raw_price(human_price, decimals0, decimals1, invert))


def get_sqrt_ratio_at_tick(tick: int) -> int:
    """Canonical Uniswap v3 ``TickMath.getSqrtRatioAtTick``, integer-exact.

    Reproduces the on-chain result bit for bit. Kept alongside the Decimal path
    in :func:`tick_to_raw_price` so the two independently cross-check each
    other: a typo in one of the magic constants below shows up immediately as a
    disagreement in ``tests/test_precision.py::test_tickmath_matches_decimal``.
    """
    reject_float(tick, "tick")
    if not isinstance(tick, int):
        raise PrecisionError("tick must be an int.")
    if not MIN_TICK <= tick <= MAX_TICK:
        raise ValueError(f"tick {tick} outside [{MIN_TICK}, {MAX_TICK}]")

    abs_tick = -tick if tick < 0 else tick

    ratio = 0xFFFCB933BD6FAD37AA2D162D1A594001 if abs_tick & 0x1 else 0x100000000000000000000000000000000
    if abs_tick & 0x2:     ratio = (ratio * 0xFFF97272373D413259A46990580E213A) >> 128
    if abs_tick & 0x4:     ratio = (ratio * 0xFFF2E50F5F656932EF12357CF3C7FDCC) >> 128
    if abs_tick & 0x8:     ratio = (ratio * 0xFFE5CACA7E10E4E61C3624EAA0941CD0) >> 128
    if abs_tick & 0x10:    ratio = (ratio * 0xFFCB9843D60F6159C9DB58835C926644) >> 128
    if abs_tick & 0x20:    ratio = (ratio * 0xFF973B41FA98C081472E6896DFB254C0) >> 128
    if abs_tick & 0x40:    ratio = (ratio * 0xFF2EA16466C96A3843EC78B326B52861) >> 128
    if abs_tick & 0x80:    ratio = (ratio * 0xFE5DEE046A99A2A811C461F1969C3053) >> 128
    if abs_tick & 0x100:   ratio = (ratio * 0xFCBE86C7900A88AEDCFFC83B479AA3A4) >> 128
    if abs_tick & 0x200:   ratio = (ratio * 0xF987A7253AC413176F2B074CF7815E54) >> 128
    if abs_tick & 0x400:   ratio = (ratio * 0xF3392B0822B70005940C7A398E4B70F3) >> 128
    if abs_tick & 0x800:   ratio = (ratio * 0xE7159475A2C29B7443B29C7FA6E889D9) >> 128
    if abs_tick & 0x1000:  ratio = (ratio * 0xD097F3BDFD2022B8845AD8F792AA5825) >> 128
    if abs_tick & 0x2000:  ratio = (ratio * 0xA9F746462D870FDF8A65DC1F90E061E5) >> 128
    if abs_tick & 0x4000:  ratio = (ratio * 0x70D869A156D2A1B890BB3DF62BAF32F7) >> 128
    if abs_tick & 0x8000:  ratio = (ratio * 0x31BE135F97D08FD981231505542FCFA6) >> 128
    if abs_tick & 0x10000: ratio = (ratio * 0x9AA508B5B7A84E1C677DE54F3E99BC9) >> 128
    if abs_tick & 0x20000: ratio = (ratio * 0x5D6AF8DEDB81196699C329225EE604) >> 128
    if abs_tick & 0x40000: ratio = (ratio * 0x2216E584F5FA1EA926041BEDFE98) >> 128
    if abs_tick & 0x80000: ratio = (ratio * 0x48A170391F7DC42444E8FA2) >> 128

    if tick > 0:
        ratio = ((1 << 256) - 1) // ratio

    # Round up when dividing down from Q128 to Q96, as the reference does.
    return (ratio >> 32) + (0 if ratio % (1 << 32) == 0 else 1)


def get_tick_at_sqrt_ratio(sqrt_price_x96: int) -> int:
    """Greatest tick whose ``getSqrtRatioAtTick`` is <= ``sqrt_price_x96``.

    Seeded from the Decimal path, then corrected against the integer TickMath
    so the answer is exact in integer terms rather than log-precision terms.
    """
    reject_float(sqrt_price_x96, "sqrt_price_x96")
    if not isinstance(sqrt_price_x96, int):
        raise PrecisionError("sqrt_price_x96 must be int.")
    seed = _raw_price_to_tick(raw_price_from_sqrt_price_x96(sqrt_price_x96))
    seed = max(MIN_TICK, min(MAX_TICK, seed))
    while seed > MIN_TICK and get_sqrt_ratio_at_tick(seed) > sqrt_price_x96:
        seed -= 1
    while seed < MAX_TICK and get_sqrt_ratio_at_tick(seed + 1) <= sqrt_price_x96:
        seed += 1
    return seed


# --------------------------------------------------------------------------- #
# Liquidity <-> token amounts (Uniswap v3 LiquidityAmounts, integer form)
# --------------------------------------------------------------------------- #

def amount0_for_liquidity(sqrt_a_x96: int, sqrt_b_x96: int, liquidity: int) -> int:
    """token0 held by ``liquidity`` between the two sqrt prices.

    ``amount0 = L * (1/sqrt(A) - 1/sqrt(B))`` in X96 integer form. Floors, as
    the pool does.
    """
    for name, v in (("sqrt_a_x96", sqrt_a_x96), ("sqrt_b_x96", sqrt_b_x96), ("liquidity", liquidity)):
        reject_float(v, name)
    if sqrt_a_x96 > sqrt_b_x96:
        sqrt_a_x96, sqrt_b_x96 = sqrt_b_x96, sqrt_a_x96
    if sqrt_a_x96 <= 0:
        raise ValueError("sqrt prices must be positive")
    return (liquidity * Q96 * (sqrt_b_x96 - sqrt_a_x96)) // (sqrt_b_x96 * sqrt_a_x96)


def amount1_for_liquidity(sqrt_a_x96: int, sqrt_b_x96: int, liquidity: int) -> int:
    """token1 held by ``liquidity`` between the two sqrt prices.

    ``amount1 = L * (sqrt(B) - sqrt(A))`` in X96 integer form. Floors.
    """
    for name, v in (("sqrt_a_x96", sqrt_a_x96), ("sqrt_b_x96", sqrt_b_x96), ("liquidity", liquidity)):
        reject_float(v, name)
    if sqrt_a_x96 > sqrt_b_x96:
        sqrt_a_x96, sqrt_b_x96 = sqrt_b_x96, sqrt_a_x96
    return (liquidity * (sqrt_b_x96 - sqrt_a_x96)) // Q96


def position_amounts(
    sqrt_p_x96: int, sqrt_lower_x96: int, sqrt_upper_x96: int, liquidity: int
) -> tuple[int, int]:
    """Token amounts of a v3 position at the current price.

    Below the range the position is entirely token0; above it, entirely token1;
    in range it holds both. Returns ``(amount0, amount1)`` in base units.
    """
    if sqrt_lower_x96 >= sqrt_upper_x96:
        raise ValueError("sqrt_lower_x96 must be strictly below sqrt_upper_x96")
    if sqrt_p_x96 <= sqrt_lower_x96:
        return amount0_for_liquidity(sqrt_lower_x96, sqrt_upper_x96, liquidity), 0
    if sqrt_p_x96 >= sqrt_upper_x96:
        return 0, amount1_for_liquidity(sqrt_lower_x96, sqrt_upper_x96, liquidity)
    return (
        amount0_for_liquidity(sqrt_p_x96, sqrt_upper_x96, liquidity),
        amount1_for_liquidity(sqrt_lower_x96, sqrt_p_x96, liquidity),
    )
