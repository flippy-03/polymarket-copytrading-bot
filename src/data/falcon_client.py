"""
Falcon / Narrative MCP Client — Prediction Market Intelligence.

Protocol: MCP over SSE (Server-Sent Events)
  1. GET /sse  → receive session_id via 'endpoint' event
  2. POST /messages/?session_id=<id>  → send JSON-RPC calls
  3. Responses arrive as 'message' events on the SSE stream

MCP Tools available:
  - authenticate                    → validate token, get user_id
  - list_data_agents                → list user's own agents
  - list_publicly_retrievable_agents → list shared/public agents
  - perform_parameterized_retrieval  → call an agent with params

Key public agents used by this bot:
  ID=575  Polymarket Market 360   — whale concentration, volume trend, winning side
  ID=556  Polymarket Trades       — individual trade executions
  ID=568  Polymarket Candlesticks — OHLC price history per token
  ID=596  Polymarket Price Jumps  — candle-to-candle moves above threshold (per market)
  ID=574  Polymarket Markets      — market search and filter
  ID=581  Wallet 360              — 60+ metric wallet profile
  ID=584  Heisenberg Leaderboard  — H-Score ranked wallets

Base URL: https://narrative.agent.heisenberg.so
Auth:     Bearer token in FALCON_BEARER_TOKEN env var
"""

import json
import queue
import threading
import time

import httpx

from src.db import supabase_client as db
from src.utils.config import FALCON_MCP_BASE, FALCON_BEARER_TOKEN
from src.utils.logger import logger

_TIMEOUT_SSE = 60.0
_TIMEOUT_POST = 10.0
_TIMEOUT_RESPONSE = 15.0


# ── Low-level MCP session ──────────────────────────────────────────────────────

class _MCPSession:
    """
    One-shot MCP session over SSE.
    Usage:
        with _MCPSession() as s:
            result = s.call_tool("perform_parameterized_retrieval", {...})
    """

    def __init__(self):
        self._base = FALCON_MCP_BASE
        self._auth = {"Authorization": f"Bearer {FALCON_BEARER_TOKEN}"}
        self._events: queue.Queue = queue.Queue()
        self._msgs_url: str | None = None
        self._ready = threading.Event()
        self._sse_thread: threading.Thread | None = None
        self._req_id = 0

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *_):
        pass  # SSE thread is daemon — dies with process

    def _start(self):
        def _reader():
            try:
                with httpx.stream(
                    "GET",
                    f"{self._base}/sse",
                    headers={**self._auth, "Accept": "text/event-stream"},
                    timeout=_TIMEOUT_SSE,
                ) as r:
                    buf: dict = {}
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            buf["event"] = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            buf["data"] = line.split(":", 1)[1].strip()
                        elif line == "" and buf:
                            self._events.put(dict(buf))
                            if buf.get("event") == "endpoint":
                                self._msgs_url = self._base + buf["data"].strip()
                                self._ready.set()
                            buf = {}
            except Exception as e:
                logger.debug(f"Falcon SSE reader exited: {e}")
                self._ready.set()  # unblock waiting callers

        self._sse_thread = threading.Thread(target=_reader, daemon=True)
        self._sse_thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Falcon SSE: no session_id received within 10s")

    def _post(self, body: dict) -> dict | None:
        if not self._msgs_url:
            return None
        try:
            httpx.post(
                self._msgs_url,
                json=body,
                headers={**self._auth, "Content-Type": "application/json"},
                timeout=_TIMEOUT_POST,
            )
        except Exception as e:
            logger.debug(f"Falcon POST failed: {e}")
            return None

        deadline = time.time() + _TIMEOUT_RESPONSE
        while time.time() < deadline:
            try:
                ev = self._events.get(timeout=0.5)
                if ev.get("event") == "message" and ev.get("data"):
                    return json.loads(ev["data"])
            except queue.Empty:
                pass
        logger.debug("Falcon: no SSE response received within timeout")
        return None

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def initialize(self):
        rid = self._next_id()
        self._post({
            "jsonrpc": "2.0", "id": rid, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "polymarket-contrarian-bot", "version": "2.0"},
            },
        })
        httpx.post(
            self._msgs_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**self._auth, "Content-Type": "application/json"},
            timeout=_TIMEOUT_POST,
        )

    def authenticate(self) -> bool:
        rid = self._next_id()
        r = self._post({
            "jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": "authenticate", "arguments": {"token": FALCON_BEARER_TOKEN}},
        })
        if not r:
            return False
        text = r.get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            data = json.loads(text)
            return data.get("status") == "success"
        except Exception:
            return False

    def call_tool(self, tool_name: str, arguments: dict) -> dict | list | None:
        """Call a tool and return parsed result data."""
        rid = self._next_id()
        r = self._post({
            "jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if not r:
            return None
        if r.get("error"):
            logger.debug(f"Falcon tool error [{tool_name}]: {r['error']}")
            return None
        content = r.get("result", {}).get("content", [])
        if not content:
            return None
        text = content[0].get("text", "")
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return text

    def retrieve(self, agent_id: int, params: dict) -> dict | list | None:
        """Shortcut for perform_parameterized_retrieval."""
        return self.call_tool("perform_parameterized_retrieval", {
            "token": FALCON_BEARER_TOKEN,
            "agent_id": agent_id,
            "params": params,
        })


_session_lock = threading.Lock()
_active_session: _MCPSession | None = None


def _get_session() -> _MCPSession:
    """
    Return a valid MCP session, creating one if needed.
    Reuses the existing session to avoid concurrent SSE connections
    (the server appears to limit to 1 active connection per token).
    """
    global _active_session
    with _session_lock:
        if _active_session is not None and _active_session._msgs_url:
            return _active_session
        s = _MCPSession()
        s._start()
        s.initialize()
        s.authenticate()
        _active_session = s
        return s


# ── Condition_id → internal UUID mapping ──────────────────────────────────────

def _map_condition_ids_to_uuids(condition_ids: list[str]) -> dict[str, str]:
    """
    Bulk-lookup condition_ids in the markets table.
    Returns {condition_id: uuid}.
    """
    if not condition_ids:
        return {}
    try:
        client = db.get_client()
        rows = (
            client.table("markets")
            .select("id,condition_id")
            .in_("condition_id", condition_ids)
            .execute()
            .data
        )
        return {r["condition_id"]: r["id"] for r in rows if r.get("condition_id")}
    except Exception as e:
        logger.debug(f"Falcon: condition_id→UUID mapping failed: {e}")
        return {}


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_herding_candidates(
    min_top1_wallet_pct: float = 30.0,
    min_volume_24h: float = 10_000.0,
) -> dict[str, dict]:
    """
    Fetch markets where a single wallet dominates volume (whale herding signal).
    Uses Agent 575 — Polymarket Market 360.

    Returns: {market_uuid: {top1_wallet_pct, direction, volume_trend, winning_side, ...}}
    Returns empty dict on any error.
    """
    if not FALCON_BEARER_TOKEN:
        logger.debug("Falcon: no bearer token — skipping herding fetch")
        return {}
    try:
        s = _get_session()
        data = s.retrieve(575, {
            "min_volume_24h":    str(int(min_volume_24h)),
            "min_top1_wallet_pct": str(int(min_top1_wallet_pct)),
            "volume_trend":      "ALL",
        })
        if not data:
            return {}

        results = data.get("data", {}).get("results", []) if isinstance(data, dict) else []
        if not results:
            return {}

        # Map condition_id → UUID
        cids = [r["condition_id"] for r in results if r.get("condition_id")]
        cid_to_uuid = _map_condition_ids_to_uuids(cids)

        out: dict[str, dict] = {}
        for item in results:
            cid = item.get("condition_id", "")
            uuid = cid_to_uuid.get(cid)
            if not uuid:
                continue  # market not in our DB

            top1_pct = float(item.get("top1_wallet_pct") or 0)
            if top1_pct < min_top1_wallet_pct:
                continue

            winning_side = item.get("winning_side")  # "Yes" / "No" / None
            # Contrarian direction: if NO wallets are winning → market oversold YES → signal YES
            direction = None
            if winning_side == "No":
                direction = "YES"
            elif winning_side == "Yes":
                direction = "NO"

            out[uuid] = {
                "top1_wallet_pct":  top1_pct,
                "top3_wallet_pct":  float(item.get("top3_wallet_pct") or 0),
                "direction":        direction,
                "winning_side":     winning_side,
                "volume_trend":     item.get("volume_trend"),
                "whale_control":    item.get("whale_control_flag", False),
                "squeeze_risk":     item.get("squeeze_risk_flag", False),
                "yes_avg_pnl":      float(item.get("yes_avg_pnl") or 0),
                "no_avg_pnl":       float(item.get("no_avg_pnl") or 0),
                "source":           "falcon_575",
            }
            logger.debug(
                f"Falcon herding: {uuid[:8]}... top1={top1_pct:.0f}% "
                f"dir={direction} trend={item.get('volume_trend')}"
            )

        if out:
            logger.info(f"Falcon Market 360: {len(out)} herding candidates (top1>{min_top1_wallet_pct:.0f}%)")
        return out

    except Exception as e:
        logger.warning(f"fetch_herding_candidates failed: {e}")
        return {}


def fetch_whale_trades(
    lookback_seconds: int = 3600,
    min_size_usd: float = 1_000.0,
) -> list[dict]:
    """
    Fetch recent large trades from Polymarket.
    Uses Agent 556 — Polymarket Trades.

    Returns list of trade dicts: {condition_id, outcome, price, proxy_wallet, side, size, slug, timestamp}
    Returns empty list on any error.
    """
    if not FALCON_BEARER_TOKEN:
        logger.debug("Falcon: no bearer token — skipping whale trades fetch")
        return []
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        start_ts = int((now - timedelta(seconds=lookback_seconds)).timestamp())
        end_ts = int(now.timestamp())

        s = _get_session()
        data = s.retrieve(556, {
            "condition_id": "ALL",
            "proxy_wallet":  "ALL",
            "side":          "ALL",
            "start_time":    str(start_ts),
            "end_time":      "2200000000",  # far future — API uses this as "now"
        })
        if not data:
            return []

        trades = data.get("data", {}).get("results", []) if isinstance(data, dict) else []
        filtered = [
            t for t in trades
            if float(t.get("size") or 0) * float(t.get("price") or 0) >= min_size_usd
        ]
        if filtered:
            logger.info(f"Falcon Trades: {len(filtered)} trades >= ${min_size_usd:,.0f}")
        return filtered

    except Exception as e:
        logger.warning(f"fetch_whale_trades failed: {e}")
        return []


def fetch_market_360(condition_id: str) -> dict | None:
    """
    Deep single-market analysis via Agent 575.
    Returns full Market 360 dict or None on error.
    Useful for position validation before entering a trade.
    """
    if not FALCON_BEARER_TOKEN:
        return None
    try:
        s = _get_session()
        data = s.retrieve(575, {"condition_id": condition_id})
        if not data:
            return None
        results = data.get("data", {}).get("results", []) if isinstance(data, dict) else []
        return results[0] if results else None
    except Exception as e:
        logger.warning(f"fetch_market_360({condition_id[:12]}...) failed: {e}")
        return None
