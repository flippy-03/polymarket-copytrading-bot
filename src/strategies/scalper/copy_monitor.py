"""
Scalper Copy Monitor — polls active titular wallets, detects fresh trades and
mirrors them proportionally via the scalper_executor.

Close behaviour: when a titular sells out of an asset that we are copying, we
close our paper trade.
"""
import time

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.scalper.scalper_executor import ScalperExecutor
from src.utils.logger import logger


class ScalperCopyMonitor:
    def __init__(self):
        self.data = DataClient()
        self.executor = ScalperExecutor(data=self.data)
        self.titulars: set[str] = set()
        self.last_seen: dict[str, int] = {}

    def close(self):
        self.executor.close()
        self.data.close()

    def refresh_titulars(self) -> None:
        rows = db.list_scalper_pool(status="ACTIVE_TITULAR")
        self.titulars = {r["wallet_address"] for r in rows}
        logger.info(f"ScalperCopyMonitor tracking {len(self.titulars)} titulars")

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
        # Data-api returns newest first; we want chronological order for mirrored execution
        return list(reversed(trades))

    def iterate_once(self) -> None:
        for wallet in list(self.titulars):
            trades = self._poll(wallet)
            for trade in trades:
                side = (trade.get("side") or "").upper()
                if side == "BUY":
                    self.executor.mirror_open(wallet, trade)
                elif side == "SELL":
                    self.executor.mirror_close(wallet, trade)
            time.sleep(0.1)

    def run_forever(self, refresh_every: int = 30) -> None:
        logger.info("ScalperCopyMonitor starting…")
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
