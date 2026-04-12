"""
Polymarket CLOB + Gamma API wrapper.
Uses the `polymarket-apis` PyPI package as primary, with direct HTTP fallback.
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from src.utils.logger import logger

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketClient:
    def __init__(self):
        self._clob = httpx.Client(base_url=CLOB_BASE, timeout=15.0)
        self._gamma = httpx.Client(base_url=GAMMA_BASE, timeout=15.0)

    def _clob_get(self, path: str, params: dict | None = None) -> Any:
        resp = self._clob.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def _gamma_get(self, path: str, params: dict | None = None) -> Any:
        resp = self._gamma.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    # ── Markets ───────────────────────────────────────────────────────────────

    def get_active_markets(
        self,
        min_volume: float = 10_000,
        limit: int = 200,
    ) -> list[dict]:
        """
        Fetch active markets from Gamma API using dual-query pattern.

        Two queries merged by conditionId:
          1. order=startDate desc  — newest markets (TTL ~24h, epoch-style)
          2. order=endDate asc     — soonest-expiring (near-resolution candidates)

        Using `active=true` in Gamma API would filter out many near-expiry and
        lower-profile markets. We use `closed=false` only to get the full set.
        """
        seen: dict[str, dict] = {}
        queries = [
            {"closed": "false", "order": "startDate", "ascending": "false",
             "volume_num_min": min_volume, "limit": limit},
            {"closed": "false", "order": "endDate",   "ascending": "true",
             "volume_num_min": min_volume, "limit": limit},
        ]
        for params in queries:
            try:
                data = self._gamma_get("/markets", params=params)
                markets = data if isinstance(data, list) else data.get("markets", [])
                for m in markets:
                    cid = m.get("conditionId")
                    if cid and cid not in seen:
                        seen[cid] = m
            except Exception as e:
                logger.error(f"get_active_markets query failed ({params['order']}): {e}")

        return [self._normalize_market(m) for m in seen.values()]

    def _normalize_market(self, raw: dict) -> dict:
        """Flatten Gamma API market into our schema shape."""
        import json as _json
        # clobTokenIds: ["yes_token_id", "no_token_id"] — index 0 = YES, 1 = NO
        # Can arrive as a Python list OR as a JSON-encoded string
        clob_ids = raw.get("clobTokenIds") or []
        if isinstance(clob_ids, str):
            try:
                clob_ids = _json.loads(clob_ids)
            except Exception:
                clob_ids = []
        yes_token = clob_ids[0] if len(clob_ids) > 0 else None
        no_token = clob_ids[1] if len(clob_ids) > 1 else None

        # outcomePrices come as strings: ["0.55", "0.45"]
        outcome_prices = raw.get("outcomePrices") or []
        def _price(val):
            try:
                return float(val) if val not in (None, "", '""') else None
            except (ValueError, TypeError):
                return None

        # Prefer endDate (full ISO with time+Z) over endDateIso (date-only, no timezone)
        end_date = raw.get("endDate") or raw.get("end_date") or raw.get("endDateIso")
        if isinstance(end_date, (int, float)):
            end_date = datetime.fromtimestamp(end_date, tz=timezone.utc).isoformat()

        # Derive category from events if available
        events = raw.get("events") or []
        category = ""
        if events and isinstance(events[0], dict):
            category = (events[0].get("category") or "").lower()

        return {
            "polymarket_id": str(raw.get("id") or raw.get("conditionId") or raw.get("slug", "")),
            "condition_id": raw.get("conditionId"),
            "question": raw.get("question") or raw.get("title") or "",
            "category": category,
            "end_date": end_date,
            "yes_token_id": yes_token,
            "no_token_id": no_token,
            "yes_price": _price(outcome_prices[0]) if len(outcome_prices) > 0 else None,
            "no_price": _price(outcome_prices[1]) if len(outcome_prices) > 1 else None,
            "volume_24h": raw.get("volume24hr") or raw.get("volumeNum") or 0,
            "liquidity": raw.get("liquidityClob") or raw.get("liquidityNum") or raw.get("liquidity") or 0,
            "num_traders": raw.get("uniqueTraders24hr") or raw.get("numTraders") or 0,
            "is_active": True,
        }

    # ── Prices & orderbook ────────────────────────────────────────────────────

    def get_price(self, token_id: str) -> float | None:
        """Midpoint price for a token (0-1)."""
        try:
            data = self._clob_get("/price", params={"token_id": token_id, "side": "BUY"})
            return float(data.get("price", 0))
        except Exception as e:
            if "404" in str(e):
                logger.debug(f"get_price({token_id[:8]}...) no CLOB book (404)")
            else:
                logger.warning(f"get_price({token_id[:8]}...) failed: {e}")
            return None

    def get_orderbook(self, token_id: str) -> dict:
        """
        Orderbook snapshot.
        Returns {best_bid, best_ask, bid_depth, ask_depth}.
        """
        try:
            raw = self._clob_get("/book", params={"token_id": token_id})
            bids = raw.get("bids", [])
            asks = raw.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None
            bid_depth = sum(float(b["size"]) for b in bids[:5])
            ask_depth = sum(float(a["size"]) for a in asks[:5])

            return {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "spread": round(best_ask - best_bid, 4) if best_bid and best_ask else None,
            }
        except Exception as e:
            if "404" in str(e):
                logger.debug(f"get_orderbook({token_id[:8]}...) no CLOB book (404)")
            else:
                logger.warning(f"get_orderbook({token_id[:8]}...) failed: {e}")
            return {}

    def close(self):
        self._clob.close()
        self._gamma.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
