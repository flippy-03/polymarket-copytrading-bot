"""
Falcon / Narrative API client.

Base URL: https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized
Method: POST with JSON body + Bearer auth
Agent IDs:
  575 — Market Insights (herding detection: top wallet concentration)
  556 — Whale Trades (recent large trades by all wallets)

NOTE: As of 2026-03-24, the parameterized endpoint returns 400 with
"step process_results failed: timestamp/category field not found".
This is a server-side Falcon pipeline issue, not a client issue.
Both functions return empty results gracefully so the signal engine
falls back to PMS Agent API + momentum without interruption.
Architecture is in place — re-enable when Falcon fixes the endpoint.
"""

import httpx

from src.utils.config import FALCON_API_URL, FALCON_BEARER_TOKEN
from src.utils.logger import logger

_TIMEOUT = 10.0


def _post(body: dict) -> list | dict | None:
    """POST to Falcon parameterized endpoint. Returns parsed data or None on error."""
    if not FALCON_BEARER_TOKEN:
        logger.debug("Falcon: no bearer token configured — skipping")
        return None
    try:
        r = httpx.post(
            FALCON_API_URL,
            json=body,
            headers={"Authorization": f"Bearer {FALCON_BEARER_TOKEN}"},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            logger.debug(f"Falcon {r.status_code}: {r.text[:200]}")
            return None
        resp = r.json()
        if resp.get("status") == "error":
            logger.debug(f"Falcon error: {resp.get('error', {}).get('message', '')[:150]}")
            return None
        return resp.get("data")
    except Exception as e:
        logger.debug(f"Falcon request failed: {e}")
        return None


def fetch_herding_candidates(
    min_top1_wallet_pct: float = 30.0,
    min_volume_24h: float = 10_000.0,
) -> dict[str, dict]:
    """
    Fetch markets where a single wallet dominates >min_top1_wallet_pct of volume.
    High concentration = probable bot/whale herding → contrarian opportunity.

    Returns: {market_id: {"top1_wallet_pct": float, "direction": "YES"|"NO"|None, ...}}
    Returns empty dict on any error.
    """
    data = _post({
        "agent_id": 575,
        "parameters": {
            "min_top1_wallet_pct": min_top1_wallet_pct,
            "min_volume_24h": min_volume_24h,
        },
    })
    if not data:
        return {}

    result: dict[str, dict] = {}
    items = data if isinstance(data, list) else data.get("markets", [])
    for item in items:
        mid = item.get("market_id") or item.get("conditionId") or ""
        if not mid:
            continue
        top1_pct = float(item.get("top1_wallet_pct") or item.get("concentration_pct") or 0)
        if top1_pct < min_top1_wallet_pct:
            continue
        result[mid] = {
            "top1_wallet_pct": top1_pct,
            "direction": item.get("dominant_direction"),  # YES/NO if available
            "volume_24h": float(item.get("volume_24h") or 0),
            "source": "falcon_575",
        }
        logger.debug(f"Falcon herding: {mid[:20]} top1={top1_pct:.0f}%")

    if result:
        logger.info(f"Falcon: {len(result)} herding candidates (top1>{min_top1_wallet_pct:.0f}%)")
    return result


def fetch_whale_trades(lookback_seconds: int = 3600, min_size_usd: float = 1_000.0) -> list[dict]:
    """
    Fetch recent large trades from all wallets via Falcon Whale Trades agent (id=556).
    Filters to trades >= min_size_usd.

    Returns list of trade dicts with at least: market_id, side, amount_usd, outcome
    Returns empty list on any error.
    """
    data = _post({
        "agent_id": 556,
        "parameters": {
            "lookback_seconds": lookback_seconds,
            "wallet_proxy": "ALL",
        },
    })
    if not data:
        return []

    trades = data if isinstance(data, list) else data.get("trades", [])
    filtered = [
        t for t in trades
        if float(t.get("amount_usd") or t.get("size_usd") or 0) >= min_size_usd
    ]
    logger.info(f"Falcon whale trades: {len(filtered)} trades >=${min_size_usd:,.0f}")
    return filtered
