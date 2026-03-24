"""
Snapshot collector: every SNAPSHOT_INTERVAL_SECONDS, captures price/orderbook
data for all active candidate markets and stores in market_snapshots.
"""

from datetime import datetime, timezone

from src.data.polymarket_client import PolymarketClient
from src.db import supabase_client as db
from src.utils.logger import logger


def collect_snapshots(markets: list[dict], whale_summary: dict | None = None) -> int:
    """
    Collect one price + orderbook snapshot for each market.
    markets: list of rows from the `markets` table (must have yes_token_id).
    whale_summary: optional dict keyed by polymarket_id with whale direction data.
    Returns number of snapshots saved.
    """
    if not markets:
        logger.warning("collect_snapshots: no markets provided")
        return 0

    pm = PolymarketClient()
    snapshots = []
    now = datetime.now(tz=timezone.utc).isoformat()

    # Build lookup: internal market UUID -> whale data
    whale_lookup: dict[str, dict] = {}
    if whale_summary:
        for market in markets:
            pid = str(market.get("polymarket_id") or "")
            if pid and pid in whale_summary:
                whale_lookup[str(market.get("id"))] = whale_summary[pid]

    try:
        for market in markets:
            market_id = market.get("id")
            yes_token = market.get("yes_token_id")
            no_token = market.get("no_token_id")

            if not market_id or not yes_token:
                continue

            try:
                yes_price = pm.get_price(yes_token)
                no_price = pm.get_price(no_token) if no_token else (1 - yes_price if yes_price else None)
                ob = pm.get_orderbook(yes_token) if yes_token else {}

                # Skip markets with no CLOB price data
                if yes_price is None:
                    continue

                snap = {
                    "market_id": market_id,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "spread": ob.get("spread"),
                    "best_bid_yes": ob.get("best_bid"),
                    "best_ask_yes": ob.get("best_ask"),
                    "bid_depth_yes": ob.get("bid_depth"),
                    "ask_depth_yes": ob.get("ask_depth"),
                    "snapshot_at": now,
                }

                # Attach whale data if available for this market
                w = whale_lookup.get(str(market_id))
                if w:
                    snap["whale_direction"] = w.get("whale_direction")
                    snap["whale_trade_count"] = w.get("whale_trade_count")
                    snap["whale_volume_usd"] = w.get("whale_volume_usd")

                snapshots.append(snap)
                yes_str = f"{yes_price:.3f}" if yes_price is not None else "?"
                no_str = f"{no_price:.3f}" if no_price is not None else "?"
                logger.debug(f"Snapshot [{market.get('question', '')[:50]}] YES={yes_str} NO={no_str}")
            except Exception as e:
                logger.warning(f"Snapshot failed for market {market_id}: {e}")

        if snapshots:
            db.insert("market_snapshots", snapshots)
            logger.info(f"Saved {len(snapshots)} snapshots")

        return len(snapshots)

    finally:
        pm.close()


def get_active_markets_from_db() -> list[dict]:
    """Fetch active candidate markets from DB that have a yes_token_id."""
    client = db.get_client()
    result = (
        client.table("markets")
        .select("*")
        .eq("is_active", True)
        .not_.is_("yes_token_id", "null")
        .execute()
    )
    return result.data
