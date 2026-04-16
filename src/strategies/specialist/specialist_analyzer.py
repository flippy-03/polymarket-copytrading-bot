"""
Specialist analyzer — cross-reference CLOB holders with the specialist DB.

For a given market, determines:
  - Which known specialists (from spec_ranking) hold YES or NO positions
  - Whether to use BD_ONLY / HYBRID / FULL_SCAN mode
  - Evaluates any unknown holders found in a scan

Returns a MarketAnalysis object used by signal_generator.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.strategies.common import config as C
from src.strategies.common.data_client import DataClient
from src.strategies.specialist.ranking_db import (
    get_known_specialists,
    record_market_seen,
)
from src.strategies.specialist.specialist_profiler import SpecialistProfile, SpecialistProfiler
from src.strategies.specialist.universe_config import market_types_for
from src.utils.logger import logger


class RoutingMode(str, Enum):
    BD_ONLY = "BD_ONLY"
    HYBRID = "HYBRID"
    FULL_SCAN = "FULL_SCAN"


@dataclass
class SideAnalysis:
    """Specialists on one side (YES or NO) of a market."""
    side: str  # "YES" or "NO"
    specialists: list[dict] = field(default_factory=list)
    avg_score: float = 0.0
    avg_hit_rate: float = 0.0
    count: int = 0

    def __post_init__(self):
        if self.specialists:
            self.count = len(self.specialists)
            self.avg_score = sum(s.get("specialist_score", 0) for s in self.specialists) / self.count
            self.avg_hit_rate = sum(s.get("hit_rate", 0) for s in self.specialists) / self.count


@dataclass
class MarketAnalysis:
    market: dict
    universe: str
    market_type: str
    routing_mode: RoutingMode
    yes_side: SideAnalysis
    no_side: SideAnalysis
    new_specialists_found: int = 0
    analysis_ts: int = field(default_factory=lambda: int(time.time()))

    @property
    def condition_id(self) -> str:
        return self.market.get("conditionId", "")

    @property
    def dominant_side(self) -> Optional[SideAnalysis]:
        """The side with more/better specialists, or None if tied."""
        if self.yes_side.count == 0 and self.no_side.count == 0:
            return None
        if self.yes_side.count > self.no_side.count:
            return self.yes_side
        if self.no_side.count > self.yes_side.count:
            return self.no_side
        if self.yes_side.avg_score > self.no_side.avg_score:
            return self.yes_side
        if self.no_side.avg_score > self.yes_side.avg_score:
            return self.no_side
        return None


class SpecialistAnalyzer:
    def __init__(self, data: DataClient, run_id: str):
        self._data = data
        self._run_id = run_id
        self._profiler = SpecialistProfiler(data)

    def analyze_market(
        self,
        market: dict,
        universe: str,
        known_specialists: list[dict],
        force_mode: Optional[RoutingMode] = None,
    ) -> Optional[MarketAnalysis]:
        """
        Cross-reference market holders with known specialists.
        Decides routing mode, scans unknowns if needed, returns MarketAnalysis.
        """
        cid = market.get("conditionId")
        if not cid:
            return None

        mtype = market.get("detected_type", "other")
        target_types = market_types_for(universe)

        # ── Fetch holders ──────────────────────────────────
        try:
            holders = self._data.get_market_holders(cid, limit=50)
        except Exception as e:
            logger.warning(f"  analyzer: get_holders({cid[:12]}…) failed: {e}")
            return None

        holder_addrs = {h.get("proxyWallet") or h.get("address"): h for h in holders if h.get("proxyWallet") or h.get("address")}

        # ── Cross-reference with known specialists ─────────
        known_map = {s["wallet"]: s for s in known_specialists}
        holders_who_are_known = {addr: spec for addr, spec in known_map.items() if addr in holder_addrs}

        known_count = len(holders_who_are_known)
        all_fresh = all(
            (time.time() - float(s.get("last_updated_ts") or 0)) < C.HYBRID_BD_ONLY_MAX_AGE_HOURS * 3600
            for s in holders_who_are_known.values()
        )
        all_high_hr = all(
            float(s.get("hit_rate") or 0) >= C.HYBRID_BD_ONLY_MIN_HR
            for s in holders_who_are_known.values()
        )

        # ── Determine routing mode ─────────────────────────
        if force_mode:
            mode = force_mode
        elif known_count >= C.HYBRID_BD_ONLY_MIN_KNOWN and all_fresh and all_high_hr:
            mode = RoutingMode.BD_ONLY
        elif known_count >= 1:
            mode = RoutingMode.HYBRID
        else:
            mode = RoutingMode.FULL_SCAN

        logger.info(
            f"  analyze {cid[:12]}… type={mtype} known={known_count} mode={mode.value}"
        )

        # ── For HYBRID / FULL_SCAN: evaluate unknown holders ──
        new_specialists: list[SpecialistProfile] = []
        if mode in (RoutingMode.HYBRID, RoutingMode.FULL_SCAN):
            unknowns = [
                addr for addr in holder_addrs
                if addr and addr not in known_map
            ][:C.SPEC_MAX_UNKNOWNS_PER_MARKET]  # Cap scan to keep tick time bounded

            for addr in unknowns:
                try:
                    sp = self._profiler.profile(addr, universe, target_types)
                    if sp:
                        from src.strategies.specialist.ranking_db import upsert_profile
                        upsert_profile(sp, self._run_id)
                        new_specialists.append(sp)
                        known_map[addr] = {
                            "wallet": addr,
                            "universe": universe,
                            "hit_rate": sp.universe_hit_rate,
                            "specialist_score": sp.specialist_score,
                            "last_updated_ts": int(time.time()),
                        }
                        holders_who_are_known[addr] = known_map[addr]
                except Exception as e:
                    logger.debug(f"  profile {addr[:10]}… failed: {e}")
                time.sleep(0.2)

        # ── Assign specialists to YES / NO sides ───────────
        # Determine which side each specialist holds
        # Holders API returns token_id; we infer YES/NO from token position
        yes_specialists = []
        no_specialists = []

        # Determine YES/NO token IDs from market
        tokens = market.get("tokens") or []
        yes_token_id = None
        no_token_id = None
        for tok in tokens:
            outcome = (tok.get("outcome") or "").upper()
            if outcome == "YES":
                yes_token_id = tok.get("token_id") or tok.get("tokenId")
            elif outcome == "NO":
                no_token_id = tok.get("token_id") or tok.get("tokenId")

        for addr, spec_data in holders_who_are_known.items():
            holder_info = holder_addrs.get(addr, {})
            token_id = holder_info.get("_token_id") or holder_info.get("token_id") or holder_info.get("tokenId")
            if yes_token_id and token_id == yes_token_id:
                yes_specialists.append(spec_data)
                record_market_seen(addr, universe, cid, "YES")
            elif no_token_id and token_id == no_token_id:
                no_specialists.append(spec_data)
                record_market_seen(addr, universe, cid, "NO")
            else:
                # Can't determine side — skip (conservative)
                pass

        return MarketAnalysis(
            market=market,
            universe=universe,
            market_type=mtype,
            routing_mode=mode,
            yes_side=SideAnalysis("YES", yes_specialists),
            no_side=SideAnalysis("NO", no_specialists),
            new_specialists_found=len(new_specialists),
        )
