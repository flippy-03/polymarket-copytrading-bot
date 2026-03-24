"""
Whale trades collector: fetches recent whale trades (>$1000) from PolymarketScan Agent API
and stores direction metadata in market_snapshots as a herding signal.

Source: PolymarketScan Agent API (action=whales, 60 req/min, no auth required)
URL: https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api

This is our v1 proxy for AI/Bot divergence detection:
- If last N whale trades all go in the same direction AND price moved >5% in 1h
  → probable herding signal

NOTE: The Public API endpoint=whale_trades was migrated to Agent API on 2026-03-24
because the Public API endpoint consistently returned empty arrays.
"""

from datetime import datetime, timezone
from collections import defaultdict

import httpx

from src.db import supabase_client as db
from src.utils.config import POLYMARKETSCAN_AGENT_API_URL
from src.utils.logger import logger


def _classify_direction(trade: dict) -> str | None:
    """Extract YES/NO direction from a whale trade."""
    outcome = (trade.get("outcome") or trade.get("side") or "").upper()
    if "YES" in outcome or outcome == "BUY":
        return "YES"
    if "NO" in outcome or outcome == "SELL":
        return "NO"
    return None


def _fetch_from_agent_api(limit: int = 50) -> list[dict]:
    """
    Fetch whale trades from PolymarketScan Agent API.
    Replaces the broken Public API endpoint=whale_trades which returned [].
    """
    try:
        r = httpx.get(
            POLYMARKETSCAN_AGENT_API_URL,
            params={"action": "whales", "limit": limit, "agent_id": "contrarian-bot"},
            timeout=15.0,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            raise ValueError(f"Agent API error: {body}")
        data = body.get("data", [])
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Agent API whale fetch failed: {e}")
        return []


def collect_whale_trades() -> dict[str, dict]:
    """
    Fetch latest whale trades from PolymarketScan Agent API.
    Returns a dict keyed by market_id (polymarket_id) with:
      {direction: YES|NO|MIXED, count: int, volume_usd: float}
    """
    try:
        trades = _fetch_from_agent_api(limit=50)
        logger.info(f"Fetched {len(trades)} whale trades (Agent API)")

        # Group by market
        by_market: dict[str, list] = defaultdict(list)
        for t in trades:
            market_key = t.get("market_id") or t.get("slug") or t.get("conditionId") or ""
            if market_key:
                by_market[market_key].append(t)

        summary: dict[str, dict] = {}
        for market_key, market_trades in by_market.items():
            directions = [_classify_direction(t) for t in market_trades]
            directions = [d for d in directions if d]
            total_vol = sum(float(t.get("size_usd") or t.get("amount") or 0) for t in market_trades)

            if not directions:
                continue

            yes_count = directions.count("YES")
            no_count = directions.count("NO")
            if yes_count > no_count * 2:
                direction = "YES"
            elif no_count > yes_count * 2:
                direction = "NO"
            else:
                direction = "MIXED"

            summary[market_key] = {
                "whale_direction": direction,
                "whale_trade_count": len(market_trades),
                "whale_volume_usd": total_vol,
            }
            logger.debug(
                f"Whale summary [{market_key[:30]}]: {direction} "
                f"({yes_count}Y/{no_count}N, ${total_vol:,.0f})"
            )

        return summary

    except Exception as e:
        logger.error(f"collect_whale_trades failed: {e}")
        return {}


def detect_herding(
    whale_summary: dict[str, dict],
    min_trades: int = 3,
    min_consensus_ratio: float = 0.80,
) -> list[str]:
    """
    Identifies markets where whale trades show strong directional herding.
    Returns list of polymarket_ids with herding detected.
    """
    herding_markets = []
    for market_key, s in whale_summary.items():
        if s["whale_trade_count"] < min_trades:
            continue
        if s["whale_direction"] in ("YES", "NO"):
            herding_markets.append(market_key)
            logger.info(
                f"Herding detected: {market_key[:40]} → {s['whale_direction']} "
                f"({s['whale_trade_count']} trades, ${s['whale_volume_usd']:,.0f})"
            )
    return herding_markets
