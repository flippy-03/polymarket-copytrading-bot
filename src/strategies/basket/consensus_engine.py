"""
Basket Consensus engine — detects when ≥80% of a basket's wallets take the same
side on the same market within a 4h window.

The engine keeps an in-memory rolling state of each wallet's latest position per
conditionId. `ingest_trade()` is driven by the monitor (polling get_wallet_activity);
`evaluate_consensus()` scans the state and emits ConsensusSignal rows.
"""
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

from src.strategies.common import config as C


@dataclass
class ConsensusSignal:
    basket_category: str
    market_condition_id: str
    market_title: str
    market_slug: str
    outcome: str                       # "Yes" | "No"
    outcome_token_id: str | None
    consensus_pct: float
    wallets_in: list[str]
    avg_entry_price: float
    earliest_entry_ts: int
    latest_entry_ts: int
    signal_ts: int
    market_volume_24h: float = 0.0
    valid: bool = True
    rejection_reason: str = ""


class ConsensusEngine:
    def __init__(self, basket_wallets: list[str], category: str):
        self.wallets: set[str] = set(basket_wallets)
        self.category = category
        # {conditionId: {wallet: {"side","outcome","price","ts","usdcSize","title","slug"}}}
        self.recent_positions: dict[str, dict[str, dict]] = defaultdict(dict)
        # Emitted signals we've already returned — avoid duplicate fires for the
        # same (cid, outcome) until the window rolls forward.
        self._emitted: dict[tuple[str, str], int] = {}

    def ingest_trade(self, trade: dict) -> None:
        wallet = trade.get("proxyWallet") or trade.get("address")
        if not wallet or wallet not in self.wallets:
            return
        cid = trade.get("conditionId")
        if not cid:
            return
        self.recent_positions[cid][wallet] = {
            "side": trade.get("side"),
            "outcome": trade.get("outcome"),
            "asset": trade.get("asset"),
            "price": float(trade.get("price") or 0),
            "ts": int(trade.get("timestamp") or time.time()),
            "usdcSize": float(trade.get("usdcSize") or 0),
            "title": trade.get("title") or "",
            "slug": trade.get("slug") or "",
        }

    def evaluate_consensus(self) -> list[ConsensusSignal]:
        signals: list[ConsensusSignal] = []
        now_ts = int(time.time())
        window = C.BASKET_TIME_WINDOW_HOURS * 3600
        basket_size = len(self.wallets) or 1

        for cid, wallet_positions in self.recent_positions.items():
            recent = {
                w: pos
                for w, pos in wallet_positions.items()
                if now_ts - pos["ts"] <= window
            }
            if len(recent) < 2:
                continue

            outcome_votes: dict[str, list[str]] = defaultdict(list)
            for w, pos in recent.items():
                if (pos.get("side") or "").upper() == "BUY" and pos.get("outcome"):
                    outcome_votes[pos["outcome"]].append(w)

            for outcome, voters in outcome_votes.items():
                # Use integer comparison to avoid floating-point edge cases.
                # e.g. basket_size=7, threshold=0.80 → ceil(5.6) = 6 voters needed.
                min_voters = math.ceil(basket_size * C.BASKET_CONSENSUS_THRESHOLD)
                if len(voters) < min_voters:
                    continue
                pct = len(voters) / basket_size

                key = (cid, outcome)
                last_emit = self._emitted.get(key, 0)
                if now_ts - last_emit < window:
                    continue

                prices = [recent[w]["price"] for w in voters]
                timestamps = [recent[w]["ts"] for w in voters]
                first = recent[voters[0]]
                title = first.get("title", "")
                slug = first.get("slug", "")
                token_id = first.get("asset")

                signals.append(
                    ConsensusSignal(
                        basket_category=self.category,
                        market_condition_id=cid,
                        market_title=title,
                        market_slug=slug,
                        outcome=outcome,
                        outcome_token_id=token_id,
                        consensus_pct=round(pct, 4),
                        wallets_in=list(voters),
                        avg_entry_price=round(sum(prices) / len(prices), 4),
                        earliest_entry_ts=min(timestamps),
                        latest_entry_ts=max(timestamps),
                        signal_ts=now_ts,
                    )
                )
                self._emitted[key] = now_ts

        return signals

    def cleanup_old_positions(self, max_age_hours: int = 24) -> None:
        cutoff = int(time.time()) - max_age_hours * 3600
        for cid in list(self.recent_positions.keys()):
            self.recent_positions[cid] = {
                w: pos for w, pos in self.recent_positions[cid].items() if pos["ts"] >= cutoff
            }
            if not self.recent_positions[cid]:
                del self.recent_positions[cid]
        # Expire old emit markers too
        self._emitted = {
            k: ts for k, ts in self._emitted.items() if ts >= cutoff
        }
