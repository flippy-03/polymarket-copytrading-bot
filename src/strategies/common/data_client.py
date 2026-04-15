"""
Data API client — wallet activity, positions, holders, market trades (no auth).

Rate limit: ~30 req/s. Pagination: limit (max 500) + offset.
"""
import time
from typing import Optional

import httpx

from src.strategies.common import config as C
from src.utils.logger import logger


class DataClient:
    def __init__(self):
        self._client = httpx.Client(base_url=C.DATA_API, timeout=15.0,
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
                    logger.warning(f"DataClient GET {path} failed: {e}")
                    raise
                time.sleep(1)

    # ── Wallet activity ─────────────────────────────────

    def get_wallet_activity(
        self,
        wallet: str,
        type_filter: str = "TRADE",
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        params = {
            "user": wallet,
            "type": type_filter,
            "limit": limit,
            "offset": offset,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._get("/activity", params) or []

    def get_all_wallet_trades(
        self,
        wallet: str,
        start: Optional[int] = None,
        max_pages: int = 20,
    ) -> list[dict]:
        all_trades: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            try:
                batch = self.get_wallet_activity(
                    wallet, type_filter="TRADE", start=start, limit=500, offset=offset
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400 and offset > 0:
                    # Data API rejects deep pagination (offset > ~3000).
                    # Return what we have rather than failing the whole wallet.
                    break
                raise
            if not batch:
                break
            all_trades.extend(batch)
            if len(batch) < 500:
                break
            offset += 500
            time.sleep(0.1)
        return all_trades

    # ── Positions ───────────────────────────────────────

    def get_wallet_positions(
        self,
        wallet: str,
        sort_by: str = "CURRENT",
        limit: int = 100,
    ) -> list[dict]:
        params = {
            "user": wallet,
            "sortBy": sort_by,
            "sortDirection": "DESC",
            "limit": limit,
        }
        return self._get("/positions", params) or []

    # ── Market holders & trades ─────────────────────────

    def get_market_holders(self, condition_id: str, limit: int = 50) -> list[dict]:
        # Data API uses "market" param; response is [{token, holders: [...]}, ...]
        params = {"market": condition_id, "limit": limit}
        tokens = self._get("/holders", params) or []
        holders: list[dict] = []
        for token_obj in tokens:
            holders.extend(token_obj.get("holders") or [])
        return holders

    def get_market_trades(self, condition_id: str, limit: int = 500) -> list[dict]:
        params = {"market": condition_id, "limit": limit}
        return self._get("/trades", params) or []

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
