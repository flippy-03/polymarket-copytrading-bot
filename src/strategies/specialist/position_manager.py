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

from src.strategies.common import clob_exec, config as C, db
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
        self._ts_activation = C.TS_ACTIVATION
        self._ts_trail = C.TS_TRAIL_PCT

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

        # ── Resolution check via CLOB ─────────────────────────
        # Use CLOB /markets/{conditionId} for exact lookup. The Gamma API
        # /markets?condition_id=… ignores the filter and returns unrelated
        # markets, making it unreliable for resolution detection.
        try:
            mkt = clob_exec.get_clob_market(cid)
            if mkt and mkt.get("closed"):
                res_price = clob_exec._get_resolution_price(mkt, token_id)
                if res_price is not None:
                    clob_exec._close_real_at_price(trade_id, res_price, "MARKET_RESOLVED")
                else:
                    # Fallback: close at current CLOB price (may be 0 for resolved markets)
                    clob_exec.close_paper_trade(trade_id, "MARKET_RESOLVED")
                return ClosureEvent(trade_id, "MARKET_RESOLVED", universe, cid)
        except Exception as e:
            logger.debug(f"  position_manager: resolution check {trade_id[:8]}: {e}")

        # ── Price-based stop checks ───────────────────────────
        # No hard stop: specialist markets (sports, crypto range/above) all
        # resolve within hours. A fixed -20% hard stop triggers on temporary
        # intra-game / intraday volatility, not on prediction errors.
        # Rely instead on: (1) trailing stop to protect accumulated gains,
        # (2) natural market resolution as the primary exit.
        # Revisit once we have ≥30 closed positions to assess P&L distribution.
        # v3.1: resilient price with Gamma fallback — avoids 80+ min sample
        # gaps when the CLOB orderbook dries up near game resolution. The
        # fallback uses Gamma's outcomePrices which survives liquidity lulls.
        current_price = clob_exec.get_token_price_resilient(token_id, cid)
        if not current_price or current_price <= 0:
            return None

        pct_change = (current_price - entry_price) / entry_price

        # ── Universe-specific stop-loss ───────────────────────
        # Only applied when configured (e.g. sports: -70%, live score is signal).
        universe_cfg = C.SPECIALIST_UNIVERSES.get(universe, {})
        sl_pct = universe_cfg.get("sl_pct")
        if sl_pct is not None and pct_change <= sl_pct:
            clob_exec.close_paper_trade(trade_id, "STOP_LOSS")
            logger.info(
                f"  SL triggered {trade_id[:8]}… universe={universe} "
                f"entry={entry_price:.3f} current={current_price:.3f} "
                f"pct={pct_change:.1%} threshold={sl_pct:.0%}"
            )
            return ClosureEvent(trade_id, "STOP_LOSS", universe, cid)

        trailing_active = bool(metadata.get("trailing_active", False))
        high_water = float(metadata.get("high_water_mark") or current_price)
        low_water = float(metadata.get("low_water_mark") or current_price)

        # Build metadata patch — always track both watermarks for backtest analysis
        patch: dict = {}
        if current_price > high_water:
            high_water = current_price
            patch["high_water_mark"] = high_water
        if current_price < low_water:
            low_water = current_price
            patch["low_water_mark"] = low_water

        # Activate trailing after +8% gain
        if not trailing_active and pct_change >= self._ts_activation:
            patch["trailing_active"] = True
            patch["high_water_mark"] = high_water
            trailing_active = True
            logger.info(
                f"  trailing ACTIVATED {trade_id[:8]}… "
                f"entry={entry_price:.3f} current={current_price:.3f}"
            )

        if patch:
            db.update_copy_trade_metadata(trade_id, patch)

        # Trailing stop check
        if trailing_active:
            trail_stop = high_water * (1 - self._ts_trail)
            if current_price <= trail_stop:
                clob_exec.close_paper_trade(trade_id, "TRAILING_STOP")
                return ClosureEvent(trade_id, "TRAILING_STOP", universe, cid)

        return None
