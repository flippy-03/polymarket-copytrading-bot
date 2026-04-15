"""
Rotation Engine — weekly selection of the active titulares from the scalper pool.

Run every Monday 00:00 UTC:
1. Re-estimate Sharpe 14d for the pool wallets.
2. Drop wallets whose 7d AND 14d PnL are both negative.
3. Exclude quarantined wallets.
4. Take the top N by Sharpe as titulars; mark the rest as POOL.
5. Log a rotation_history row for audit.
"""
import datetime
import time

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.scalper.pool_builder import estimate_sharpe_14d
from src.utils.logger import logger


def _sum_pnl(trades: list[dict], days: int) -> float:
    now_ts = int(time.time())
    cutoff = now_ts - days * 86400
    pnl = 0.0
    for t in trades:
        ts = int(t.get("timestamp") or 0)
        if ts < cutoff:
            continue
        usdc = float(t.get("usdcSize") or 0)
        if (t.get("side") or "").upper() == "SELL":
            pnl += usdc
        else:
            pnl -= usdc
    return pnl


class RotationEngine:
    def __init__(self):
        self.data = DataClient()

    def close(self):
        self.data.close()

    def execute_rotation(self, reason: str = "SCHEDULED_WEEKLY") -> dict:
        logger.info(f"Scalper rotation: {reason}")
        pool = db.list_scalper_pool()
        if not pool:
            logger.warning("scalper_pool is empty — cannot rotate")
            return {"new_titulars": [], "removed_titulars": []}

        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )

        # Recompute Sharpe + PnL windows per pool wallet
        metrics: dict[str, dict] = {}
        for row in pool:
            addr = row["wallet_address"]
            if row.get("status") == "QUARANTINE":
                continue
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
            except Exception as e:
                logger.warning(f"  trades({addr[:10]}) failed: {e}")
                continue
            metrics[addr] = {
                "sharpe": estimate_sharpe_14d(trades),
                "pnl_7d": _sum_pnl(trades, 7),
                "pnl_14d": _sum_pnl(trades, 14),
            }
            time.sleep(0.15)

        current_titulars = [r["wallet_address"] for r in pool if r.get("status") == "ACTIVE_TITULAR"]

        # Drop titulars with both 7d and 14d negative
        removed: list[dict] = []
        retained: list[str] = []
        for addr in current_titulars:
            m = metrics.get(addr, {})
            if m.get("pnl_7d", 0) < 0 and m.get("pnl_14d", 0) < 0:
                removed.append({"wallet": addr, "pnl_7d": m.get("pnl_7d"), "pnl_14d": m.get("pnl_14d"),
                                "sharpe_14d": m.get("sharpe")})
            else:
                retained.append(addr)

        # Rank all eligible wallets by Sharpe
        eligible = [addr for addr in metrics.keys()]
        eligible.sort(key=lambda a: metrics[a]["sharpe"], reverse=True)
        new_titulars = eligible[:C.SCALPER_ACTIVE_WALLETS]

        # Capital allocation (equal split of scalper portfolio capital)
        p = db.get_portfolio("SCALPER")
        total_cap = float((p or {}).get("current_capital") or C.SCALPER_INITIAL_CAPITAL)
        per_wallet = round(total_cap / max(len(new_titulars), 1), 2) if new_titulars else 0.0

        # Persist status changes
        titular_set = set(new_titulars)
        for row in pool:
            addr = row["wallet_address"]
            if row.get("status") == "QUARANTINE":
                continue
            if addr in titular_set:
                db.update_scalper_status(addr, "ACTIVE_TITULAR", capital_usd=per_wallet)
            else:
                db.update_scalper_status(addr, "POOL", capital_usd=0)

        # Rotation audit row
        new_titulars_payload = [
            {"wallet": a, "sharpe_14d": metrics[a]["sharpe"], "allocated_usd": per_wallet}
            for a in new_titulars
        ]
        pool_snapshot = [
            {"wallet": a, **metrics[a]} for a in eligible
        ]
        try:
            db.insert_rotation(
                reason=reason,
                removed_titulars=removed,
                new_titulars=new_titulars_payload,
                pool_snapshot=pool_snapshot,
            )
        except Exception as e:
            logger.warning(f"insert_rotation failed: {e}")

        logger.info(
            f"Rotation done: {len(new_titulars)} titulars, {len(removed)} removed, "
            f"${per_wallet:.2f}/wallet"
        )
        return {
            "new_titulars": new_titulars,
            "removed_titulars": [r["wallet"] for r in removed],
            "per_wallet_allocation": per_wallet,
        }
