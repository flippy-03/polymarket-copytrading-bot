"""
Market scanner — find active markets by type that resolve within the target window.

Uses Gamma API to search for markets, then filters locally by:
  - endDate ≤ now + SPECIALIST_MARKET_MAX_HOURS
  - volume ≥ SPECIALIST_MARKET_MIN_VOLUME_24H
  - price ∈ [SPECIALIST_MARKET_MIN_PRICE, SPECIALIST_MARKET_MAX_PRICE] (via CLOB)

The price filter requires 1 CLOB request per market (done lazily in analyzer).
"""
from __future__ import annotations

import datetime
import time

from src.strategies.common import config as C
from src.strategies.common.gamma_client import GammaClient
from src.strategies.specialist.market_type_classifier import classify
from src.utils.logger import logger


def find_candidate_markets(
    market_types: list[str],
    gamma: GammaClient,
    max_hours: float = C.SPECIALIST_MARKET_MAX_HOURS,
    min_volume: float = C.SPECIALIST_MARKET_MIN_VOLUME_24H,
    limit_per_type: int = 10,
) -> list[dict]:
    """
    Scan Gamma API for active markets that:
      1. Resolve within `max_hours`
      2. Meet the minimum 24h volume
      3. Classify into one of `market_types`

    Returns a list of market dicts enriched with 'detected_type'.
    Markets are deduplicated by conditionId.
    """
    cutoff = datetime.datetime.utcnow() + datetime.timedelta(hours=max_hours)
    cutoff_iso = cutoff.isoformat() + "Z"

    seen: set[str] = set()
    candidates: list[dict] = []

    # Paginate active markets, filter locally
    offset = 0
    page_size = 100

    while len(candidates) < limit_per_type * len(market_types):
        try:
            batch = gamma.get_active_markets(
                min_volume_24h=min_volume,
                limit=page_size,
                offset=offset,
            )
        except Exception as e:
            logger.warning(f"  market_scanner: get_active_markets failed: {e}")
            break

        if not batch:
            break

        for m in batch:
            cid = m.get("conditionId")
            if not cid or cid in seen:
                continue

            # Resolution window filter
            end_date = m.get("endDate") or "9999"
            if end_date > cutoff_iso:
                continue

            # Type filter
            mtype = classify(m)
            if mtype not in market_types:
                continue

            seen.add(cid)
            m["detected_type"] = mtype
            candidates.append(m)

        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(0.1)

    logger.info(
        f"  market_scanner: {len(candidates)} candidates "
        f"(types={market_types}, ≤{max_hours:.0f}h)"
    )
    return candidates
