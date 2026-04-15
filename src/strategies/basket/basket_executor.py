"""
Basket Executor — consumes pending consensus_signals and opens paper trades;
monitors OPEN basket trades for exit when ≥BASKET_EXIT_CONSENSUS of the source
wallets sell back out of the position.

All writes are scoped to the ACTIVE run of the BASKET strategy. Each real trade
is mirrored by a shadow trade (fixed $100, no risk gating). On every tick:
  - real OPEN trades get exited if ≥BASKET_EXIT_CONSENSUS of the basket sells
  - shadow OPEN trades evaluate virtual stop-loss / take-profit
  - when a shadow's pair has exited (or its own basket consensus breaks), the
    shadow 'pure' side is closed too
"""
import time

from src.db import supabase_client as _db
from src.strategies.common import config as C, clob_exec, db, risk_manager_ct as risk
from src.strategies.common.data_client import DataClient
from src.utils.logger import logger


class BasketExecutor:
    STRATEGY = "BASKET"

    def __init__(self):
        self.data = DataClient()
        self.run_id = db.get_active_run(self.STRATEGY)
        db.ensure_portfolio_row(
            self.STRATEGY, run_id=self.run_id, is_shadow=True,
            initial_capital=C.BASKET_INITIAL_CAPITAL, max_open_positions=C.MAX_OPEN_POSITIONS,
        )

    def close(self):
        self.data.close()

    # ── entries ──────────────────────────────────────────

    def _position_size(self) -> float:
        """Equal slice within MAX_CAPITAL_PCT of the basket strategy capital."""
        p = db.get_portfolio(self.STRATEGY, run_id=self.run_id)
        if not p:
            return 0.0
        capital = float(p["current_capital"])
        slice_pct = min(C.MAX_PER_TRADE_PCT, C.BASKET_MAX_CAPITAL_PCT / max(C.MAX_OPEN_POSITIONS, 1))
        return round(capital * slice_pct, 2)

    def execute_pending(self) -> int:
        pending = db.list_pending_signals(run_id=self.run_id)
        executed = 0
        for sig in pending:
            token_id = sig.get("outcome_token_id")
            if not token_id:
                logger.warning(f"[BASKET] signal {sig['id'][:8]} missing outcome_token_id — skipping")
                _db.update("consensus_signals", match={"id": sig["id"]},
                           data={"status": "REJECTED", "rejection_reason": "no_outcome_token_id"})
                continue

            size = self._position_size()
            if size < 5:
                size = 5.0  # minimum for the real attempt; clob_exec still gates by risk

            result = clob_exec.open_paper_trade(
                strategy=self.STRATEGY,
                market_polymarket_id=sig["market_polymarket_id"],
                outcome_token_id=token_id,
                direction=sig["direction"],
                size_usd=size,
                run_id=self.run_id,
                signal_id=sig["id"],
                market_question=sig.get("market_question"),
                market_category=None,
                metadata={
                    "consensus_pct": float(sig.get("consensus_pct") or 0),
                    "wallets_agreeing": int(sig.get("wallets_agreeing") or 0),
                    "wallets_total": int(sig.get("wallets_total") or 0),
                    "basket_id": sig["basket_id"],
                },
            )
            if result.get("real") or result.get("shadow"):
                db.mark_signal_executed(sig["id"])
                executed += 1
            else:
                _db.update("consensus_signals", match={"id": sig["id"]},
                           data={"status": "REJECTED", "rejection_reason": "execution_failed"})
        return executed

    # ── exits ────────────────────────────────────────────

    def _basket_still_holds(self, basket_id: str, token_id: str) -> bool:
        """Return True if ≥BASKET_EXIT_CONSENSUS of the basket members still hold token_id."""
        wallets = db.get_active_basket_wallets(basket_id, run_id=self.run_id)
        if not wallets:
            return False
        holders = 0
        for w in wallets:
            try:
                positions = self.data.get_wallet_positions(w, limit=100)
            except Exception:
                continue
            for p in positions:
                if p.get("asset") == token_id and float(p.get("size") or 0) > 0:
                    holders += 1
                    break
            time.sleep(0.05)
        ratio = holders / len(wallets)
        return ratio >= C.BASKET_EXIT_CONSENSUS

    def _check_trades(self, *, is_shadow: bool) -> int:
        """Evaluate basket-consensus exit for OPEN trades of the given kind."""
        open_trades = db.list_open_trades(strategy=self.STRATEGY, run_id=self.run_id, is_shadow=is_shadow)
        closed = 0
        for t in open_trades:
            token_id = t.get("outcome_token_id")
            basket_id = (t.get("metadata") or {}).get("basket_id")
            if not token_id or not basket_id:
                continue
            if not self._basket_still_holds(basket_id, token_id):
                if is_shadow:
                    clob_exec.close_shadow_trade(t["id"], reason="BASKET_EXIT_CONSENSUS")
                else:
                    clob_exec.close_paper_trade(t["id"], reason="BASKET_EXIT_CONSENSUS")
                closed += 1
        return closed

    def check_exits(self) -> tuple[int, int]:
        real_closed = self._check_trades(is_shadow=False)
        shadow_closed = self._check_trades(is_shadow=True)
        return real_closed, shadow_closed

    # ── loop ─────────────────────────────────────────────

    def run_forever(self) -> None:
        logger.info(f"BasketExecutor starting… run={self.run_id[:8]}")
        while True:
            try:
                self.execute_pending()
                self.check_exits()
                clob_exec.evaluate_shadow_stops(self.STRATEGY, run_id=self.run_id)
            except Exception as e:
                logger.exception(f"BasketExecutor iteration error: {e}")
            time.sleep(C.BASKET_MONITOR_INTERVAL_SECONDS)
