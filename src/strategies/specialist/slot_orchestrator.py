"""
Slot orchestrator — the main event loop for Specialist Edge (spec §9).

On each tick():
  1. Check all open positions (resolution + trailing stops)
  2. Count open trades per universe
  3. For each universe with a free slot → route → execute best signal
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.specialist.anti_blindness import AntiBlindness
from src.strategies.specialist.hybrid_router import HybridRouter
from src.strategies.specialist.position_manager import ClosureEvent, PositionManager
from src.strategies.specialist.trade_executor import execute_signal
from src.strategies.specialist.universe_config import UNIVERSES, max_slots
from src.utils.logger import logger

STRATEGY = "SPECIALIST"


class SlotOrchestrator:
    def __init__(
        self,
        gamma: GammaClient,
        data: DataClient,
        run_id: str,
    ):
        self._gamma = gamma
        self._data = data
        self._run_id = run_id
        self._position_manager = PositionManager(gamma, run_id)
        self._anti_blindness = AntiBlindness()
        self._router = HybridRouter(gamma, data, run_id, self._anti_blindness)

    def tick(self) -> dict:
        """
        One orchestration cycle. Returns a summary dict for logging.
        """
        summary = {
            "closures": [],
            "opened": [],
            "skipped": [],
        }

        # Step 1 — Check open positions
        closures: list[ClosureEvent] = self._position_manager.check_all_open()
        summary["closures"] = [c.reason for c in closures]

        # Step 2 — Count open trades per universe
        open_by_universe = self._count_open_per_universe()
        logger.info(
            f"  orchestrator: open per universe: "
            + ", ".join(f"{u}={n}" for u, n in open_by_universe.items())
        )

        # Step 3 — Fill free slots
        portfolio = db.get_portfolio(STRATEGY, run_id=self._run_id)
        total_capital = float((portfolio or {}).get("current_capital") or C.SPECIALIST_INITIAL_CAPITAL)

        for universe in UNIVERSES:
            slots = max_slots(universe)
            currently_open = open_by_universe.get(universe, 0)
            free_slots = slots - currently_open

            if free_slots <= 0:
                continue

            logger.info(
                f"  orchestrator: {universe} has {free_slots} free slot(s) — routing…"
            )

            try:
                signals = self._router.route(universe)
            except Exception as e:
                logger.warning(f"  orchestrator: route({universe}) failed: {e}")
                continue

            for signal in signals:
                if free_slots <= 0:
                    break
                try:
                    result = execute_signal(signal, self._run_id, total_capital)
                    if result and result.get("real"):
                        summary["opened"].append(f"{universe}/{signal.direction}")
                        free_slots -= 1
                    else:
                        summary["skipped"].append(f"{universe}/{signal.direction}")
                except Exception as e:
                    logger.warning(f"  orchestrator: execute_signal failed: {e}")

        return summary

    def _count_open_per_universe(self) -> dict[str, int]:
        """Count open SPECIALIST trades per universe (from metadata.universe)."""
        try:
            open_trades = db.list_open_trades(
                strategy=STRATEGY,
                run_id=self._run_id,
                is_shadow=False,
            )
        except Exception:
            return {}

        counts: Counter = Counter()
        for trade in open_trades:
            metadata = trade.get("metadata") or {}
            universe = metadata.get("universe")
            if universe:
                counts[universe] += 1

        return dict(counts)
