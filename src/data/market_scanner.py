"""
Market scanner: merges Polymarket (CLOB/Gamma) + PolymarketScan data,
filters candidates, and upserts into the `markets` table.
"""

from datetime import datetime, timezone, timedelta

from src.data.polymarket_client import PolymarketClient
from src.data.polymarketscan_client import PolymarketScanClient
from src.db import supabase_client as db
from src.utils.config import (
    MIN_VOLUME_24H,
    MIN_LIQUIDITY,
    MIN_HOURS_TO_RESOLUTION,
    MAX_HOURS_TO_RESOLUTION,
    EXCLUDED_CATEGORIES,
    SPORTS_QUESTION_KEYWORDS,
)
from src.utils.logger import logger


def _hours_to_resolution(end_date_str: str | None) -> float | None:
    if not end_date_str:
        return None
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        return (end - now).total_seconds() / 3600
    except Exception:
        return None


def _is_candidate(market: dict) -> bool:
    if float(market.get("volume_24h") or 0) < MIN_VOLUME_24H:
        return False
    if float(market.get("liquidity") or 0) < MIN_LIQUIDITY:
        return False
    cat = (market.get("category") or "").lower()
    if any(excl in cat for excl in EXCLUDED_CATEGORIES):
        return False
    # Fallback: category field is often empty — detect sports by question keywords
    question_lower = (market.get("question") or "").lower()
    if any(kw in question_lower for kw in SPORTS_QUESTION_KEYWORDS):
        return False
    hours = _hours_to_resolution(market.get("end_date"))
    if hours is not None:
        if hours < MIN_HOURS_TO_RESOLUTION or hours > MAX_HOURS_TO_RESOLUTION:
            return False
    return True


def scan_markets() -> list[dict]:
    """
    Fetch active markets, filter candidates, upsert to DB.
    Returns list of candidate market rows.
    """
    pm = PolymarketClient()
    pms = PolymarketScanClient()

    try:
        logger.info("Scanning active markets...")
        all_markets: list[dict] = []

        # Fetch from Gamma API (paginated)
        offset = 0
        while True:
            batch = pm.get_active_markets(min_volume=MIN_VOLUME_24H, limit=100, offset=offset)
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < 100:
                break
            offset += 100

        # Enrich with PolymarketScan data if Gamma returns little volume data
        if len(all_markets) < 20:
            logger.info("Gamma returned few markets — supplementing with PolymarketScan")
            pms_markets = pms.get_markets(limit=100)
            for pm_market in pms_markets:
                pms_id = str(pm_market.get("id") or pm_market.get("slug") or "")
                if not any(m["polymarket_id"] == pms_id for m in all_markets):
                    all_markets.append({
                        "polymarket_id": pms_id,
                        "question": pm_market.get("question") or pm_market.get("title") or "",
                        "category": (pm_market.get("category") or "").lower(),
                        "end_date": pm_market.get("end_date") or pm_market.get("endDate"),
                        "volume_24h": pm_market.get("volume_24h") or pm_market.get("volume24h") or 0,
                        "liquidity": pm_market.get("liquidity") or 0,
                        "is_active": True,
                    })

        candidates = [m for m in all_markets if _is_candidate(m)]
        logger.info(f"Total markets: {len(all_markets)} | Candidates: {len(candidates)}")

        if candidates:
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            numeric_fields = {"yes_price", "no_price", "volume_24h", "liquidity", "num_traders"}
            rows = []
            for m in candidates:
                row = {**m, "updated_at": now_iso}
                for k, v in row.items():
                    if k in numeric_fields:
                        # Coerce to float or None — catch empty string, '""', False, etc.
                        try:
                            row[k] = float(v) if v not in (None, "", '""', False) else None
                        except (ValueError, TypeError):
                            logger.debug(f"Dropping invalid numeric [{k}]={v!r}")
                            row[k] = None
                    elif v == "":
                        row[k] = None
                rows.append(row)
            db.upsert("markets", rows, on_conflict="polymarket_id")
            logger.info(f"Upserted {len(candidates)} candidate markets")

        return candidates

    except Exception as e:
        logger.error(f"scan_markets failed: {e}")
        return []
    finally:
        pm.close()
        pms.close()
