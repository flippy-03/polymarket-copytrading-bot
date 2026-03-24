"""
PolymarketScan API client with rate limiting and retry logic.

Base URL: https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api
Rate limit: 30 requests/minute
Response format: {"ok": true, "data": {...}, "response_time_ms": 142}
"""

import time
import threading
from collections import deque
from typing import Any

import httpx

from src.utils.config import POLYMARKETSCAN_API_URL, POLYMARKETSCAN_API_KEY
from src.utils.logger import logger

# ── Rate limiter: 30 req / 60 s sliding window ────────────────────────────────

class _RateLimiter:
    def __init__(self, max_calls: int = 30, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._lock = threading.Lock()
        self._timestamps: deque = deque()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            # Drop timestamps older than the window
            while self._timestamps and self._timestamps[0] < now - self.period:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_calls:
                sleep_for = self.period - (now - self._timestamps[0])
                if sleep_for > 0:
                    logger.debug(f"Rate limit: sleeping {sleep_for:.1f}s")
                    time.sleep(sleep_for)

            self._timestamps.append(time.monotonic())


_limiter = _RateLimiter(max_calls=28, period=60.0)  # 28 to be safe


# ── HTTP client ────────────────────────────────────────────────────────────────

class PolymarketScanClient:
    def __init__(self):
        self._http = httpx.Client(
            base_url=POLYMARKETSCAN_API_URL,
            headers={"x-api-key": POLYMARKETSCAN_API_KEY},
            timeout=15.0,
        )

    def _get(self, params: dict, retries: int = 3) -> Any:
        """Make a GET request with rate limiting and exponential backoff."""
        _limiter.wait()
        for attempt in range(retries):
            try:
                resp = self._http.get("", params=params)
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    raise ValueError(f"API error: {body}")
                return body["data"]
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 60 * (attempt + 1)
                    logger.warning(f"429 Too Many Requests — waiting {wait}s")
                    time.sleep(wait)
                else:
                    logger.error(f"HTTP {e.response.status_code}: {e}")
                    raise
            except (httpx.RequestError, ValueError) as e:
                if attempt == retries - 1:
                    raise
                wait = 2 ** attempt
                logger.warning(f"Request failed ({e}), retry {attempt+1}/{retries} in {wait}s")
                time.sleep(wait)

    # ── Data endpoints ────────────────────────────────────────────────────────

    def get_markets(self, limit: int = 100, offset: int = 0, category: str | None = None) -> list[dict]:
        """
        Markets list sorted by 24h volume.
        Returns list of market dicts.
        """
        params = {"endpoint": "markets", "limit": min(limit, 100), "offset": offset}
        if category:
            params["category"] = category
        data = self._get(params)
        # API returns {"markets": [...]} or just a list
        if isinstance(data, list):
            return data
        return data.get("markets", data.get("data", []))

    def get_market_data(self, slug: str | None = None, market_id: str | None = None) -> dict:
        """
        Detailed data for a single market.
        Pass slug (e.g. 'will-bitcoin-hit-100k') or market_id.
        """
        params = {"endpoint": "market_data"}
        if slug:
            params["slug"] = slug
        elif market_id:
            params["market_id"] = market_id
        else:
            raise ValueError("Provide slug or market_id")
        return self._get(params)

    def get_leaderboard(self, limit: int = 100) -> list[dict]:
        """Top traders by PnL."""
        params = {"endpoint": "leaderboard", "limit": min(limit, 100)}
        data = self._get(params)
        if isinstance(data, list):
            return data
        return data.get("leaderboard", data.get("data", []))

    def get_whale_trades(self, limit: int = 50) -> list[dict]:
        """Recent trades > $1,000."""
        params = {"endpoint": "whale_trades", "limit": min(limit, 50)}
        data = self._get(params)
        if isinstance(data, list):
            return data
        return data.get("trades", data.get("data", []))

    def get_wallet_profile(self, address: str) -> dict:
        """Stats for a wallet: PnL, volume, win rate, best trade."""
        params = {"endpoint": "wallet_profile", "address": address}
        return self._get(params)

    def get_wallet_trades(self, address: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """Paginated trade history for a wallet."""
        params = {
            "endpoint": "wallet_trades",
            "address": address,
            "limit": min(limit, 500),
            "offset": offset,
        }
        data = self._get(params)
        if isinstance(data, list):
            return data
        return data.get("trades", data.get("data", []))

    def get_wallet_pnl(self, address: str) -> dict:
        """P&L summary + daily timeseries for a wallet."""
        params = {"endpoint": "wallet_pnl", "address": address}
        return self._get(params)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
