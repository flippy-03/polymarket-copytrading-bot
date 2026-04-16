"""
Position manager — trailing stop + market resolution checks (spec §10).

Trailing stop mechanics:
  - Hard stop: -20% from entry → close immediately
  - Activation: after +8% gain, trailing stop activates
  - Trail: close if price drops 15% below high-water mark

State persisted in copy_trades.metadata JSON (survives daemon restart):
  {
    "trailing_active": bool,
    "high_water_mark": float | None,
    "universe": str,
    ...
  }

Resolution detection: poll gamma_client.get_market(cid) every tick.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from src.strategies.common import clob_exec, db
from src.strategies.common.gamma_client import GammaClient
from src.utils.logger import logger

STRATEGY = "SPECIALIST"


@dataclass
class ClosureEvent:
    trade_id: str
    reason: str
    universe: str
    condition_id: str


class PositionManager:
    def __init__(self, gamma: GammaClient, run_id: str):
        self._gamma = gamma
        self._run_id = run_id
        from src.strategies.common import config as C
        self._ts_activation = C.TS_ACTIVATION
        self._ts_trail = C.TS_TRAIL_PCT
        self._ts_hard_stop = C.TS_HARD_STOP

    def check_all_open(self) -> list[ClosureEvent]:
        """
        Evaluate all open SPECIALIST trades for resolution/stops.
        Returns list of ClosureEvent for each closed position.
        """
        try:
            open_trades = db.list_open_trades(
                strategy=STRATEGY,
                run_id=self._run_id,
                is_shadow=False,
            )
        except Exception as e:
            logger.warning(f"  position_manager: list_open_trades failed: {e}")
            return []

        closures: list[ClosureEvent] = []
        for trade in open_trades:
            event = self._check_trade(trade)
            if event:
                closures.append(event)
            time.sleep(0.1)

        if closures:
            logger.info(
                f"  position_manager: closed {len(closures)} positions: "
                + ", ".join(e.reason for e in closures)
            )
        return closures

    def _check_trade(self, trade: dict) -> Optional[ClosureEvent]:
        trade_id = trade["id"]
        cid = trade.get("market_polymarket_id", "")
        token_id = trade.get("outcome_token_id", "")
        entry_price = float(trade.get("entry_price") or 0)
        metadata = trade.get("metadata") or {}
        universe = metadata.get("universe", "unknown")

        if entry_price <= 0 or not token_id:
            return None

        # ── Resolution check ──────────────────────────────────
        try:
            mkt = self._gamma.get_market(cid)
            if mkt and mkt.get("closed"):
                clob_exec.close_paper_trade(trade_id, "RESOLVED")
                return ClosureEvent(trade_id, "RESOLVED", universe, cid)
        except Exception as e:
            logger.debug(f"  position_manager: resolution check {trade_id[:8]}: {e}")

        # ── Price-based stop checks ───────────────────────────
        current_price = clob_exec.get_token_price(token_id)
        if not current_price or current_price <= 0:
            return None

        pct_change = (current_price - entry_price) / entry_price

        # Hard stop
        if pct_change <= self._ts_hard_stop:
            clob_exec.close_paper_trade(trade_id, "STOP_LOSS")
            return ClosureEvent(trade_id, "STOP_LOSS", universe, cid)

        trailing_active = bool(metadata.get("trailing_active", False))
        high_water = float(metadata.get("high_water_mark") or current_price)

        # Update high-water mark if price moved up
        if current_price > high_water:
            high_water = current_price
            db.update_copy_trade_metadata(trade_id, {"high_water_mark": high_water})

        # Activate trailing after +8% gain
        if not trailing_active and pct_change >= self._ts_activation:
            db.update_copy_trade_metadata(
                trade_id, {"trailing_active": True, "high_water_mark": high_water}
            )
            logger.info(
                f"  trailing ACTIVATED {trade_id[:8]}… "
                f"entry={entry_price:.3f} current={current_price:.3f}"
            )
            trailing_active = True

        # Trailing stop check
        if trailing_active:
            trail_stop = high_water * (1 - self._ts_trail)
            if current_price <= trail_stop:
                clob_exec.close_paper_trade(trade_id, "TRAILING_STOP")
                return ClosureEvent(trade_id, "TRAILING_STOP", universe, cid)

        return None
