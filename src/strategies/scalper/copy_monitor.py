"""
Scalper V2 Copy Monitor — polls titular wallets, filters by approved market
types, and mirrors trades with portfolio-relative sizing.

Key V2 changes:
  - Market type filtering: only copy trades in approved types per titular
  - Trailing stop per position (reused from specialist position_manager pattern)
  - Shadow overflow: when capital/risk is blocked, open shadow instead of skip
  - Per-titular circuit breaker check before copying
  - Resolution detection every RESOLUTION_CHECK_EVERY ticks
"""
import time
from datetime import datetime, timezone

from src.strategies.common import clob_exec, config as C, db
from src.strategies.common import risk_manager_ct as risk
from src.strategies.common.data_client import DataClient
from src.strategies.scalper.scalper_executor import ScalperExecutor
from src.strategies.specialist.market_type_classifier import classify
from src.utils.logger import logger

RESOLUTION_CHECK_EVERY = 5
TRAILING_ACTIVATION = C.TS_ACTIVATION   # +8% gain
TRAILING_TRAIL_PCT = C.TS_TRAIL_PCT     # 15% below HWM

# v3.1 hard-stop rules: applied only while trailing is NOT active (trailing
# takes over once the trade has cleared +8%). Sports get a wider stop
# because late-game volatility is noise, not model error.
_SPORTS_TYPES = frozenset({
    "sports_winner", "sports_spread", "sports_total", "sports_futures",
})


def _hard_stop_for(market_category: str | None) -> float:
    """Return the hard-stop threshold (negative float) to apply to a trade
    of the given market_category."""
    if market_category in _SPORTS_TYPES:
        return C.SPORTS_HARD_STOP_PCT
    return C.TS_HARD_STOP


class ScalperCopyMonitor:
    STRATEGY = "SCALPER"

    def __init__(self):
        self.data = DataClient()
        self.run_id = db.get_active_run(self.STRATEGY)
        self.executor = ScalperExecutor(data=self.data, run_id=self.run_id)
        self.titulars: dict[str, dict] = {}  # wallet → pool entry (with approved_market_types)
        self.last_seen: dict[str, int] = {}
        self._tick = 0

    def close(self):
        self.executor.close()
        self.data.close()

    def refresh_titulars(self) -> None:
        """Load active titulars with their approved market types from scalper_pool."""
        rows = db.list_scalper_pool(status="ACTIVE_TITULAR", run_id=self.run_id)
        self.titulars = {}
        for r in rows:
            wallet = r["wallet_address"]
            self.titulars[wallet] = {
                "approved_market_types": r.get("approved_market_types") or [],
                "per_trader_is_broken": r.get("per_trader_is_broken", False),
            }
        logger.info(
            f"ScalperCopyMonitor tracking {len(self.titulars)} titulars "
            f"(V2 with type filtering)"
        )

    def _record_observed(self, wallet: str, trades: list[dict]) -> None:
        for tr in trades:
            ts = int(tr.get("timestamp") or 0)
            traded_at_iso = (
                datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
            )
            outcome = (tr.get("outcome") or "").strip()
            direction = "YES" if outcome.lower().startswith("y") else "NO"
            db.record_observed_trade(
                wallet_address=wallet,
                tx_hash=tr.get("transactionHash") or tr.get("txHash"),
                traded_at=traded_at_iso,
                market_polymarket_id=tr.get("conditionId") or "",
                market_question=tr.get("title") or tr.get("question"),
                outcome_token_id=tr.get("asset"),
                outcome_label=outcome,
                direction=direction,
                side=(tr.get("side") or "").upper() or None,
                price=float(tr.get("price") or 0) or None,
                size=float(tr.get("size") or 0) or None,
                usdc_size=float(tr.get("usdcSize") or 0) or None,
                raw=tr,
            )

    def _poll(self, wallet: str) -> list[dict]:
        start = self.last_seen.get(wallet) or (int(time.time()) - 3600)
        try:
            trades = self.data.get_wallet_activity(wallet, start=start, limit=100)
        except Exception as e:
            logger.warning(f"  poll {wallet[:10]}… failed: {e}")
            return []
        if trades:
            mx = max(int(t.get("timestamp") or 0) for t in trades)
            if mx > 0:
                self.last_seen[wallet] = mx + 1
        self._record_observed(wallet, trades)
        return list(reversed(trades))

    def _should_copy(self, titular: str, trade: dict) -> tuple[bool, str]:
        """Determine if a BUY trade should be copied as real or filtered.

        Returns (should_copy_real, reason).
        Reasons: "approved", "type_filtered", "titular_broken", "global_risk",
                 "allocation_exhausted".
        """
        titular_info = self.titulars.get(titular, {})
        approved_types = titular_info.get("approved_market_types", [])

        # 1. Classify market type
        market_type = classify(trade)

        # 2. Check if market type is approved for this titular
        if market_type not in approved_types:
            return False, "type_filtered"

        # 3. Check per-titular circuit breaker
        if risk.is_titular_broken(titular, run_id=self.run_id):
            return False, "titular_broken"

        # 4. Check global risk
        can_open, reason = risk.can_open_position(self.STRATEGY, run_id=self.run_id)
        if not can_open:
            return False, f"global_risk:{reason}"

        return True, "approved"

    def _evaluate_trailing_stops(self) -> int:
        """Evaluate trailing stops on all open real trades."""
        open_trades = db.list_open_trades(
            strategy=self.STRATEGY, run_id=self.run_id, is_shadow=False,
        )
        closed = 0
        for trade in open_trades:
            trade_id = trade["id"]
            token_id = trade.get("outcome_token_id", "")
            entry_price = float(trade.get("entry_price") or 0)
            metadata = trade.get("metadata") or {}

            if entry_price <= 0 or not token_id:
                continue

            current_price = clob_exec.get_token_price(token_id)
            if not current_price or current_price <= 0:
                continue

            pct_change = (current_price - entry_price) / entry_price
            trailing_active = bool(metadata.get("trailing_active", False))
            high_water = float(metadata.get("high_water_mark") or current_price)

            # Update high-water mark
            if current_price > high_water:
                high_water = current_price
                db.update_copy_trade_metadata(trade_id, {"high_water_mark": high_water})

            # Activate trailing after +8% gain
            if not trailing_active and pct_change >= TRAILING_ACTIVATION:
                db.update_copy_trade_metadata(
                    trade_id, {"trailing_active": True, "high_water_mark": high_water}
                )
                logger.info(
                    f"  trailing ACTIVATED {trade_id[:8]}… "
                    f"entry={entry_price:.3f} current={current_price:.3f}"
                )
                trailing_active = True

            # Trailing stop (active) OR hard stop (trailing not yet active).
            # Option B from the v3.1 postmortem: hard-stop covers trades that
            # only moved in one direction (never earned the +8% that unlocks
            # the trailing logic). Threshold differs by market_category —
            # sports get −40%, rest get −20%.
            if trailing_active:
                trail_stop = high_water * (1 - TRAILING_TRAIL_PCT)
                if current_price <= trail_stop:
                    clob_exec.close_paper_trade(trade_id, "TRAILING_STOP")
                    closed += 1
            else:
                # market_type lives in metadata (scalper_executor writes it
                # there); market_category column is optional. Metadata is
                # the reliable source.
                market_type = metadata.get("market_type")
                hard_stop = _hard_stop_for(market_type)
                if pct_change <= hard_stop:
                    clob_exec.close_paper_trade(trade_id, "STOP_LOSS")
                    closed += 1
                    logger.info(
                        f"  STOP_LOSS {trade_id[:8]}… "
                        f"pct={pct_change:+.1%} threshold={hard_stop:+.0%} "
                        f"type={market_type}"
                    )

        return closed

    def iterate_once(self) -> None:
        self._tick += 1
        for wallet in list(self.titulars.keys()):
            trades = self._poll(wallet)
            for trade in trades:
                side = (trade.get("side") or "").upper()
                if side == "BUY":
                    should_copy, reason = self._should_copy(wallet, trade)
                    if should_copy:
                        self.executor.mirror_open(wallet, trade)
                    elif reason == "type_filtered":
                        # Filtered by type → ignore entirely (no shadow)
                        pass
                    else:
                        # Blocked by risk/capital → shadow trade
                        self.executor.mirror_open(
                            wallet, trade,
                            force_shadow=True, shadow_reason=reason,
                        )
                elif side == "SELL":
                    self.executor.mirror_close(wallet, trade)
            time.sleep(0.1)

        # Evaluate shadow stops (SL/TP on shadow trades)
        clob_exec.evaluate_shadow_stops(self.STRATEGY, run_id=self.run_id)

        # Evaluate trailing stops on real trades
        self._evaluate_trailing_stops()

        # Resolution detection every N ticks
        if self._tick % RESOLUTION_CHECK_EVERY == 0:
            n = clob_exec.resolve_expired_trades(self.STRATEGY, run_id=self.run_id)
            if n:
                logger.info(f"ScalperCopyMonitor: resolved {n} expired trade(s)")

    def run_forever(self, refresh_every: int = 30) -> None:
        logger.info(f"ScalperCopyMonitor V2 starting… run={self.run_id[:8]}")
        self.refresh_titulars()
        iteration = 0
        while True:
            try:
                self.iterate_once()
            except Exception as e:
                logger.exception(f"ScalperCopyMonitor iteration error: {e}")
            iteration += 1
            if iteration % refresh_every == 0:
                self.refresh_titulars()
            time.sleep(C.SCALPER_MONITOR_INTERVAL_SECONDS)
