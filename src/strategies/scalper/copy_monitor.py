"""
Scalper Copy Monitor — polls active titular wallets, detects fresh trades and
mirrors them proportionally via the scalper_executor.

Close behaviour: when a titular sells out of an asset that we are copying, we
close our paper trade. On every tick, virtual stop-loss / take-profit is
evaluated on OPEN shadow trades via the executor.

Resolution detection: every RESOLUTION_CHECK_EVERY ticks the monitor queries
Gamma API for each open position's market. If a market has resolved (closed=true)
the position is settled at 1.0 (win) or 0.0 (loss) without requiring an
explicit SELL from the titular — sports/binary markets often resolve by
expiration rather than an on-chain sell.
"""
import time
from datetime import datetime, timezone

from src.strategies.common import clob_exec, config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.scalper.scalper_executor import ScalperExecutor
from src.utils.logger import logger

# Check for market resolution every N ticks (avoids hammering CLOB on every tick).
RESOLUTION_CHECK_EVERY = 5


class ScalperCopyMonitor:
    STRATEGY = "SCALPER"

    def __init__(self):
        self.data = DataClient()
        self.run_id = db.get_active_run(self.STRATEGY)
        self.executor = ScalperExecutor(data=self.data, run_id=self.run_id)
        self.titulars: set[str] = set()
        self.last_seen: dict[str, int] = {}
        self._tick = 0

    def close(self):
        self.executor.close()
        self.data.close()

    def refresh_titulars(self) -> None:
        rows = db.list_scalper_pool(status="ACTIVE_TITULAR", run_id=self.run_id)
        self.titulars = {r["wallet_address"] for r in rows}
        logger.info(f"ScalperCopyMonitor tracking {len(self.titulars)} titulars")

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
        # Data-api returns newest first; we want chronological order for mirrored execution
        return list(reversed(trades))

    def iterate_once(self) -> None:
        self._tick += 1
        for wallet in list(self.titulars):
            trades = self._poll(wallet)
            for trade in trades:
                side = (trade.get("side") or "").upper()
                if side == "BUY":
                    self.executor.mirror_open(wallet, trade)
                elif side == "SELL":
                    self.executor.mirror_close(wallet, trade)
            time.sleep(0.1)
        clob_exec.evaluate_shadow_stops(self.STRATEGY, run_id=self.run_id)
        # Check for market resolution periodically — handles sports/binary markets
        # that settle by expiration rather than an explicit titular SELL.
        if self._tick % RESOLUTION_CHECK_EVERY == 0:
            n = clob_exec.resolve_expired_trades(self.STRATEGY, run_id=self.run_id)
            if n:
                logger.info(f"ScalperCopyMonitor: resolved {n} expired trade(s)")

    def run_forever(self, refresh_every: int = 30) -> None:
        logger.info(f"ScalperCopyMonitor starting… run={self.run_id[:8]}")
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
