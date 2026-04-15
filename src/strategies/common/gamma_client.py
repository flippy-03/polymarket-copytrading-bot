"""
Gamma API client — market and tag discovery (no auth).

Rate limits: ~4000 req/10s general, 500/10s for /events, 300/10s for /markets.
"""
import time
import datetime
from typing import Optional

import httpx

from src.strategies.common import config as C
from src.utils.logger import logger


class GammaClient:
    def __init__(self):
        self._client = httpx.Client(base_url=C.GAMMA_API, timeout=15.0,
                                    headers={"Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None):
        for attempt in range(3):
            try:
                r = self._client.get(path, params=params or {})
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.HTTPError as e:
                if attempt == 2:
                    logger.warning(f"GammaClient GET {path} failed: {e}")
                    raise
                time.sleep(1)

    # ── Tags / categories ────────────────────────────────

    def get_all_tags(self) -> list[dict]:
        return self._get("/tags") or []

    def discover_category_tags(self) -> dict[str, list[int]]:
        """
        Maps each category to a list of Gamma tag ids by keyword match on
        label/slug. Returns {"crypto": [...], "politics": [...], "economics": [...]}.
        """
        all_tags = self.get_all_tags()
        result = {cat: [] for cat in C.CATEGORY_KEYWORDS}
        for tag in all_tags:
            label = (tag.get("label") or "").lower()
            slug = (tag.get("slug") or "").lower()
            combined = f"{label} {slug}"
            for cat, keywords in C.CATEGORY_KEYWORDS.items():
                if any(kw in combined for kw in keywords):
                    tag_id = tag.get("id")
                    if tag_id and tag_id not in result[cat]:
                        result[cat].append(tag_id)
        return result

    # ── Markets ──────────────────────────────────────────

    def get_active_markets(
        self,
        tag_id: Optional[int] = None,
        min_volume_24h: float = C.MIN_LIQUIDITY_24H,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
            "limit": limit,
            "offset": offset,
        }
        if tag_id is not None:
            params["tag"] = tag_id  # Gamma API uses "tag", not "tag_id"
        markets = self._get("/markets", params) or []
        if not markets:
            return []
        # Gamma API may use different field names across versions; try all known ones.
        def _vol(m: dict) -> float:
            return float(
                m.get("volume24hr")
                or m.get("volume24Hr")
                or m.get("volume_24hr")
                or m.get("volumeClob")
                or m.get("volume")
                or 0
            )
        if min_volume_24h > 0:
            # Debug: log once to surface the actual field names in the response
            first = markets[0]
            vol_fields = {k: v for k, v in first.items() if "vol" in k.lower()}
            if not vol_fields:
                logger.debug(f"Gamma market keys (no vol field found): {list(first.keys())}")
            else:
                logger.debug(f"Gamma volume fields: {vol_fields}")
        return [m for m in markets if _vol(m) >= min_volume_24h]

    def get_events_by_tag(
        self,
        tag_id: int,
        limit: int = 50,
        active_only: bool = True,
    ) -> list[dict]:
        params = {
            "tag_id": tag_id,
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false",
        }
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        return self._get("/events", params) or []

    def get_markets_resolving_within(self, days: int = 7) -> list[dict]:
        """
        Active markets whose endDate is within `days` from now.
        Gamma has no endDate-range filter, so we paginate + filter locally.
        """
        cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        cutoff_iso = cutoff.isoformat() + "Z"

        all_markets = []
        offset = 0
        while True:
            batch = self.get_active_markets(limit=100, offset=offset, min_volume_24h=0)
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < 100:
                break
            offset += 100

        result = [
            m for m in all_markets
            if (m.get("endDate") or "9999") <= cutoff_iso
        ]
        return sorted(result, key=lambda m: m.get("volume24hr") or 0, reverse=True)

    def get_resolved_markets(
        self,
        tag_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Recently resolved (closed=true) markets for a given tag.
        These markets have outcomePrices showing who won — useful for
        identifying wallets that correctly predicted outcomes.
        """
        params = {
            "active": "false",
            "closed": "true",
            "order": "volume",
            "ascending": "false",
            "limit": limit,
        }
        if tag_id is not None:
            params["tag"] = tag_id
        return self._get("/markets", params) or []

    def get_market_by_slug(self, slug: str) -> dict:
        return self._get(f"/markets/slug/{slug}")

    def get_market_by_id(self, market_id: int) -> dict:
        return self._get(f"/markets/{market_id}")

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
