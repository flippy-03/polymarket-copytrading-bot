"""
Hybrid router — orchestrates the full routing flow for one universe slot.

Flow (spec §7):
  A. Query type rankings to pick best market type to target
  B. Fetch known specialists from spec_ranking
  C. Scan Gamma for candidate markets of that type
  D. Cross-reference each market with specialists
  E. Generate signal per market
  F. Return best signal sorted by expected_roi
"""
from __future__ import annotations

import time
from typing import Optional

from src.strategies.common import config as C
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.specialist.anti_blindness import AntiBlindness
from src.strategies.specialist.market_scanner import find_candidate_markets
from src.strategies.specialist.ranking_db import get_known_specialists
from src.strategies.specialist.signal_generator import Signal, generate_signal
from src.strategies.specialist.specialist_analyzer import (
    MarketAnalysis,
    RoutingMode,
    SpecialistAnalyzer,
)
from src.strategies.specialist.type_rankings import get_type_priority
from src.strategies.specialist.universe_config import market_types_for
from src.utils.logger import logger


class HybridRouter:
    def __init__(
        self,
        gamma: GammaClient,
        data: DataClient,
        run_id: str,
        anti_blindness: Optional[AntiBlindness] = None,
    ):
        self._gamma = gamma
        self._data = data
        self._run_id = run_id
        self._ab = anti_blindness or AntiBlindness()
        self._analyzer = SpecialistAnalyzer(data, run_id)

    def route(self, universe: str) -> list[Signal]:
        """
        Find the best tradeable signal for an open slot in `universe`.
        Returns a list of actionable signals sorted by expected_roi DESC.
        """
        market_types = market_types_for(universe)
        if not market_types:
            logger.warning(f"  router: unknown universe {universe}")
            return []

        # A — Best market type by priority score
        type_priority = get_type_priority(market_types)
        logger.info(
            f"  router [{universe}] type priorities: "
            + ", ".join(f"{t}={s:.2f}" for t, s in type_priority)
        )

        all_signals: list[Signal] = []

        for mtype, _priority in type_priority:
            # B — Known specialists
            known = get_known_specialists(universe)

            # C — Scan Gamma for candidates
            candidates = find_candidate_markets(
                market_types=[mtype],
                gamma=self._gamma,
                limit_per_type=8,
            )
            if not candidates:
                logger.info(f"  router [{mtype}]: no candidates found")
                continue

            # D+E — Analyze + generate signals
            for market in candidates:
                try:
                    # Anti-blindness: force FULL_SCAN periodically
                    force_mode = None
                    if self._ab.should_force_scan(universe):
                        force_mode = RoutingMode.FULL_SCAN
                        logger.info(f"  anti_blindness: forcing FULL_SCAN for {universe}")

                    analysis = self._analyzer.analyze_market(
                        market=market,
                        universe=universe,
                        known_specialists=known,
                        force_mode=force_mode,
                    )
                    if not analysis:
                        continue

                    # Track anti-blindness counter
                    if analysis.routing_mode == RoutingMode.BD_ONLY:
                        self._ab.record_bd_only(universe)
                    else:
                        self._ab.record_scan(universe)

                    signal = generate_signal(analysis)
                    if signal and signal.is_actionable:
                        all_signals.append(signal)
                        logger.info(
                            f"  signal [{signal.quality.value}] {signal.condition_id[:12]}… "
                            f"dir={signal.direction} specialists={signal.specialists_for}/{signal.specialists_against} "
                            f"ratio={signal.ratio:.1f} eROI={signal.expected_roi:.1%} "
                            f"cROI={signal.compound_roi:.1%}"
                        )
                except Exception as e:
                    logger.warning(f"  router analyze failed: {e}")
                time.sleep(0.15)

        # F — Sort: CLEAN first, then by compound_roi DESC within each tier.
        # compound_roi = expected_roi × time_bonus, so shorter-duration markets
        # at equal expected_roi rank higher. Entry gates are unchanged.
        all_signals.sort(
            key=lambda s: (
                s.quality.value == "CLEAN",  # True > False
                s.compound_roi,
            ),
            reverse=True,
        )
        logger.info(
            f"  router [{universe}]: {len(all_signals)} actionable signals"
        )
        return all_signals
