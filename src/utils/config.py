"""Load `config.yaml` and resolve paths. One source of truth for every constant.

Nothing in `src/` may hard-code a number that appears in `config.yaml`. If a
value is needed and is not in the config, add it to the config rather than
inlining it — the reproducibility requirement is that every figure is
regenerable from the config plus the code.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass(frozen=True)
class TokenSpec:
    symbol: str
    decimals: int
    address: str


@dataclass(frozen=True)
class PoolSpec:
    """One pool in the universe. `token0`/`token1` are ADDRESS-SORTED."""

    id: str
    address: str
    token0: TokenSpec
    token1: TokenSpec
    fee_tier_bps: int
    tick_spacing: int
    invert_price: bool
    verified_on_etherscan: bool
    #: Binance symbol whose price is directly comparable to this pool's, and
    #: whether it must be inverted first. Hard-coding ETHUSDT worked while the
    #: universe was one asset pair and silently breaks the moment it is not.
    cex_symbol: str = "ETHUSDT"
    cex_invert: bool = False
    #: Which token exposures a delta hedge must cover, and the perp for each.
    #: Empty means the pool has no USD price risk to hedge (a stable/stable
    #: pool); more than one entry means a single perp cannot do it. Hedging a
    #: USDC delta with an ETH perp produced a funding figure of -9,856%.
    hedge_legs: tuple = ()
    #: First month with liquidity, "YYYY-MM". A pool listed later than the
    #: sample start has no data before this and fetching it wastes hours on
    #: empty ranges; more importantly, an empty month is not a quiet month and
    #: must not enter a table as one.
    first_month: str | None = None

    @property
    def first_ym(self) -> tuple[int, int] | None:
        if not self.first_month:
            return None
        y, m = self.first_month.split("-")
        return int(y), int(m)

    def covers(self, year: int, month: int) -> bool:
        """Is (year, month) inside this pool's own sample?"""
        fy = self.first_ym
        return fy is None or (year, month) >= fy

    @property
    def hedge_map(self) -> dict:
        return dict(self.hedge_legs)

    @property
    def fee_rate(self) -> Decimal:
        """Fee as a fraction, exact. 30bp -> Decimal('0.003')."""
        return Decimal(self.fee_tier_bps) / Decimal(10_000)

    def require_verified(self) -> None:
        """Guard for Stage 1.1: no pool is used before Etherscan verification."""
        if not self.verified_on_etherscan:
            raise RuntimeError(
                f"Pool {self.id} ({self.address}) has verified_on_etherscan=false. "
                f"Confirm the address, token order and decimals on Etherscan, then "
                f"flip the flag in config.yaml. Address-sorted token order is the "
                f"single most common source of an inverted price."
            )


@functools.lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> dict[str, Any]:
    """Parse `config.yaml`. Cached; call `load_config.cache_clear()` in tests."""
    with open(path or CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def _pool_from_dict(d: dict[str, Any]) -> PoolSpec:
    return PoolSpec(
        id=d["id"],
        address=d["address"].lower(),
        token0=TokenSpec(**d["token0"]),
        token1=TokenSpec(**d["token1"]),
        fee_tier_bps=d["fee_tier_bps"],
        tick_spacing=d["tick_spacing"],
        invert_price=d["invert_price"],
        verified_on_etherscan=d["verified_on_etherscan"],
        cex_symbol=d.get("cex_symbol", "ETHUSDT"),
        cex_invert=bool(d.get("cex_invert", False)),
        hedge_legs=tuple(sorted((d.get("hedge_legs") or {}).items())),
        first_month=d.get("first_month"),
    )


def pools(scope: str = "core") -> list[PoolSpec]:
    """Universe pools. `scope` is 'core', 'extension' or 'all'.

    Core is the H4 natural experiment and is the only scope permitted until the
    Stage 1-3 gates pass end to end.
    """
    cfg = load_config()["universe"]
    if scope == "all":
        entries = cfg["core"] + cfg["extension"]
    else:
        entries = cfg[scope]
    return [_pool_from_dict(d) for d in entries]


def pool(pool_id: str) -> PoolSpec:
    for p in pools("all"):
        if p.id == pool_id:
            return p
    raise KeyError(f"unknown pool id {pool_id!r}")


def path(key: str) -> Path:
    """Resolve a configured path relative to the repo root, creating it."""
    p = REPO_ROOT / load_config()["paths"][key]
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.suffix:
        p.mkdir(parents=True, exist_ok=True)
    return p


def seconds_per_year() -> int:
    return int(load_config()["annualisation"]["seconds_per_year"])


def annualise(rate_per_period: Decimal, period_seconds: int) -> Decimal:
    """Scale a simple per-period rate to a per-year rate.

    The single annualisation convention, stated in `config.yaml` and applied
    here. Do not annualise inline anywhere else.
    """
    if isinstance(rate_per_period, float):
        raise TypeError("annualise() takes Decimal, not float")
    return rate_per_period * Decimal(seconds_per_year()) / Decimal(period_seconds)
