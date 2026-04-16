"""
Universe configuration for Specialist Edge.

Universes define the set of market types the bot operates in, their capital
allocation, and slot limits. Tag IDs are discovered dynamically from Gamma API
(same approach as former basket_builder); this module provides the static config.
"""
from src.strategies.common import config as C

# Expose the SPECIALIST_UNIVERSES constant for convenience.
UNIVERSES = C.SPECIALIST_UNIVERSES

# Market types that each universe covers — derived from UNIVERSES for fast lookup.
UNIVERSE_FOR_TYPE: dict[str, str] = {}
for _universe, _cfg in UNIVERSES.items():
    for _mtype in _cfg["market_types"]:
        UNIVERSE_FOR_TYPE[_mtype] = _universe

# All supported market types across all universes.
OPERABLE_TYPES: set[str] = set(UNIVERSE_FOR_TYPE.keys())


def universe_capital(universe: str, total_capital: float) -> float:
    """Capital allocated to a universe given total portfolio capital."""
    pct = UNIVERSES.get(universe, {}).get("capital_pct", 0.0)
    return total_capital * pct


def max_slots(universe: str) -> int:
    return UNIVERSES.get(universe, {}).get("max_slots", 0)


def market_types_for(universe: str) -> list[str]:
    return UNIVERSES.get(universe, {}).get("market_types", [])
