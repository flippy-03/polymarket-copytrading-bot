"""
Anti-blindness counter — forces periodic FULL_SCAN to avoid tunnel vision.

When the DB has sufficient specialists, the router can spend many consecutive
ticks in BD_ONLY mode, never discovering new wallets. This module counts
consecutive BD_ONLY decisions and forces a FULL_SCAN every N cycles.
"""
from src.strategies.common import config as C


class AntiBlindness:
    """
    Tracks consecutive BD_ONLY routing decisions per universe and forces
    a FULL_SCAN every ANTI_BLINDNESS_FORCE_SCAN_EVERY decisions.
    """

    def __init__(self):
        self._counters: dict[str, int] = {}

    def record_bd_only(self, universe: str) -> None:
        self._counters[universe] = self._counters.get(universe, 0) + 1

    def record_scan(self, universe: str) -> None:
        """Reset counter after any HYBRID or FULL_SCAN."""
        self._counters[universe] = 0

    def should_force_scan(self, universe: str) -> bool:
        """Return True if we should override BD_ONLY with FULL_SCAN."""
        return self._counters.get(universe, 0) >= C.ANTI_BLINDNESS_FORCE_SCAN_EVERY

    def get_counter(self, universe: str) -> int:
        return self._counters.get(universe, 0)
