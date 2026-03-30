"""
Entry point: Paper Trading loop — Phase 3.

  - Every 60s: check open positions (trailing stop, take profit, timeout, resolution)
  - Every 60s: scan for new ACTIVE signals and open trades
  - Every 300s: print portfolio summary

Run alongside run_collector.py and run_signal_engine.py.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import schedule
from datetime import datetime, timezone

from src.db import supabase_client as db
from src.trading.paper_trader import open_trade, open_shadow_trade
from src.trading.position_manager import check_open_positions, check_shadow_positions
from src.trading.portfolio_tracker import print_portfolio_summary, get_open_trades
from src.trading.risk_manager import get_portfolio_state, is_trading_allowed
from src.utils.logger import logger


def job_check_positions():
    """Check all open positions for stop/TP/timeout/resolution."""
    closed = check_open_positions()
    check_shadow_positions()
    if closed:
        logger.info(f"Closed {closed} position(s) this cycle")


def job_open_new_trades():
    """Find ACTIVE signals and open paper trades."""
    client = db.get_client()
    state = get_portfolio_state(client)
    if not state:
        return

    # Get ACTIVE signals not yet traded
    signals = (
        client.table("signals")
        .select("*")
        .eq("status", "ACTIVE")
        .order("total_score", desc=True)
        .limit(10)
        .execute()
        .data
    )

    if not signals:
        logger.debug("No active signals to trade")
        return

    allowed, reason = is_trading_allowed(state)

    if not allowed:
        logger.info(f"New trades blocked: {reason}")
        # Capacity block — open shadow trades so signal quality is tracked
        shadows = 0
        for signal in signals:
            if open_shadow_trade(signal, reason):
                shadows += 1
        if shadows:
            logger.info(f"Opened {shadows} shadow trade(s) (blocked: {reason})")
        return

    # Check which markets already have an open trade (avoid duplicates)
    open_trades = get_open_trades()
    open_market_ids = {t["market_id"] for t in open_trades}

    new_trades = 0
    for signal in signals:
        if signal["market_id"] in open_market_ids:
            continue

        trade = open_trade(signal)
        if trade:
            new_trades += 1
            open_market_ids.add(signal["market_id"])

    if new_trades:
        logger.info(f"Opened {new_trades} new trade(s)")


def job_portfolio_summary():
    """Log portfolio state."""
    print_portfolio_summary()


def main():
    logger.info("=" * 60)
    logger.info("Polymarket Contrarian Bot — Phase 3: Paper Trader")
    logger.info("=" * 60)

    db.verify_connection()
    print_portfolio_summary()

    # Schedule
    schedule.every(60).seconds.do(job_check_positions)
    schedule.every(60).seconds.do(job_open_new_trades)
    schedule.every(300).seconds.do(job_portfolio_summary)

    logger.info("Paper trader started. Press Ctrl+C to stop.")
    logger.info("  Position check:  every 60s")
    logger.info("  New trade scan:  every 60s")
    logger.info("  Portfolio log:   every 5 min")

    # Run immediately
    job_check_positions()
    job_open_new_trades()

    while True:
        schedule.run_pending()
        time.sleep(5)


if __name__ == "__main__":
    main()
