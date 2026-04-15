"""
Basket Monitor — polls wallet activity for every basket's members, feeds the
ConsensusEngine and persists consensus signals when threshold is reached.

One BasketMonitor instance runs per process and handles all active baskets. The
main loop sleeps BASKET_MONITOR_INTERVAL_SECONDS between polls. Each wallet is
polled only for trades newer than the last seen timestamp to minimize API load.
"""
import time
from datetime import datetime, timezone

from src.strategies.basket.consensus_engine import ConsensusEngine, ConsensusSignal
from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.utils.logger import logger


class BasketMonitor:
    def __init__(self):
        self.data = DataClient()
        # engines keyed by basket_id
        self.engines: dict[str, ConsensusEngine] = {}
        self.basket_meta: dict[str, dict] = {}   # basket_id -> {"category": ...}
        # last_seen_ts per wallet (across all baskets) — dedupes polling
        self.last_seen: dict[str, int] = {}

    def close(self):
        self.data.close()

    # ── basket state ─────────────────────────────────────

    def refresh_baskets(self) -> None:
        """Reload the active baskets and rebuild the engine map."""
        active = db.list_active_baskets()
        new_engines: dict[str, ConsensusEngine] = {}
        new_meta: dict[str, dict] = {}
        for b in active:
            bid = b["id"]
            wallets = db.get_active_basket_wallets(bid)
            if len(wallets) < 2:
                logger.info(f"Basket {b.get('category')} has <2 wallets, skipping")
                continue
            # Preserve existing engine state if the wallet set is unchanged
            prev = self.engines.get(bid)
            if prev and prev.wallets == set(wallets):
                new_engines[bid] = prev
            else:
                new_engines[bid] = ConsensusEngine(wallets, b.get("category") or "UNKNOWN")
            new_meta[bid] = {"category": b.get("category")}
        self.engines = new_engines
        self.basket_meta = new_meta
        logger.info(f"BasketMonitor tracking {len(self.engines)} active baskets")

    # ── polling ──────────────────────────────────────────

    def _poll_wallet(self, wallet: str) -> list[dict]:
        start = self.last_seen.get(wallet) or (int(time.time()) - C.BASKET_TIME_WINDOW_HOURS * 3600)
        try:
            trades = self.data.get_wallet_activity(wallet, start=start, limit=100)
        except Exception as e:
            logger.warning(f"  poll {wallet[:10]}… failed: {e}")
            return []
        if trades:
            max_ts = max(int(t.get("timestamp") or 0) for t in trades)
            if max_ts > 0:
                self.last_seen[wallet] = max_ts + 1
        return trades

    def poll_once(self) -> list[tuple[str, ConsensusSignal]]:
        """Poll all tracked wallets once and return (basket_id, signal) pairs."""
        polled: set[str] = set()
        for bid, engine in self.engines.items():
            for wallet in engine.wallets:
                if wallet in polled:
                    continue
                polled.add(wallet)
                for trade in self._poll_wallet(wallet):
                    engine.ingest_trade(trade)
                time.sleep(0.05)

        fresh: list[tuple[str, ConsensusSignal]] = []
        for bid, engine in self.engines.items():
            for sig in engine.evaluate_consensus():
                fresh.append((bid, sig))
            engine.cleanup_old_positions()
        return fresh

    # ── persistence ──────────────────────────────────────

    def persist_signal(self, basket_id: str, sig: ConsensusSignal) -> str:
        engine = self.engines.get(basket_id)
        wallets_total = len(engine.wallets) if engine else len(sig.wallets_in)
        direction = "YES" if (sig.outcome or "").lower().startswith("y") else "NO"
        row = {
            "basket_id": basket_id,
            "market_polymarket_id": sig.market_condition_id,
            "market_question": sig.market_title,
            "direction": direction,
            "outcome_token_id": sig.outcome_token_id,
            "consensus_pct": round(sig.consensus_pct, 4),
            "wallets_agreeing": len(sig.wallets_in),
            "wallets_total": wallets_total,
            "window_start": datetime.fromtimestamp(sig.earliest_entry_ts, tz=timezone.utc).isoformat(),
            "window_end": datetime.fromtimestamp(sig.latest_entry_ts, tz=timezone.utc).isoformat(),
            "price_at_signal": sig.avg_entry_price,
            "status": "PENDING",
        }
        sid = db.insert_consensus_signal(row)
        logger.info(
            f"[BASKET/{sig.basket_category}] consensus {sig.consensus_pct:.0%} on "
            f"{sig.market_title[:60]!r} → {direction} (signal {sid[:8]})"
        )
        return sid

    # ── loop ─────────────────────────────────────────────

    def run_forever(self, refresh_every: int = 20) -> None:
        logger.info("BasketMonitor starting…")
        self.refresh_baskets()
        iteration = 0
        while True:
            try:
                signals = self.poll_once()
                for bid, sig in signals:
                    self.persist_signal(bid, sig)
            except Exception as e:
                logger.exception(f"BasketMonitor iteration error: {e}")
            iteration += 1
            if iteration % refresh_every == 0:
                self.refresh_baskets()
            time.sleep(C.BASKET_MONITOR_INTERVAL_SECONDS)
