"""
Portfolio Tracker — prints current portfolio state and performance stats.
"""

from src.db import supabase_client as db
from src.trading.risk_manager import get_portfolio_state
from src.utils.logger import logger


def print_portfolio_summary() -> dict:
    """Log current portfolio state. Returns state dict."""
    client = db.get_client()
    state = get_portfolio_state(client)
    if not state:
        logger.warning("No portfolio state found")
        return {}

    initial = float(state.get("initial_capital", 1000))
    current = float(state.get("current_capital", 1000))
    total_pnl = float(state.get("total_pnl", 0))
    total_pnl_pct = float(state.get("total_pnl_pct", 0))
    win_rate = float(state.get("win_rate", 0))
    total_trades = state.get("total_trades", 0)
    winning = state.get("winning_trades", 0)
    losing = state.get("losing_trades", 0)
    open_pos = state.get("open_positions", 0)
    max_dd = float(state.get("max_drawdown", 0))
    circuit_broken = state.get("is_circuit_broken", False)

    logger.info("=" * 50)
    logger.info("PORTFOLIO SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Capital:       ${initial:.2f} -> ${current:.2f}")
    logger.info(f"Total P&L:     ${total_pnl:+.2f} ({total_pnl_pct:+.1%})")
    logger.info(f"Trades:        {total_trades} total | {winning}W {losing}L | {win_rate:.0%} win rate")
    logger.info(f"Open pos:      {open_pos}")
    logger.info(f"Max drawdown:  {max_dd:.1%}")
    logger.info(f"Circuit:       {'BROKEN [X]' if circuit_broken else 'OK [v]'}")
    logger.info("=" * 50)

    return state


def get_open_trades() -> list[dict]:
    """Return all open paper trades with market question."""
    client = db.get_client()
    trades = (
        client.table("paper_trades")
        .select("*, markets(question)")
        .eq("status", "OPEN")
        .execute()
        .data
    )
    return trades


def get_closed_trades(limit: int = 20) -> list[dict]:
    """Return recent closed trades ordered by close time."""
    client = db.get_client()
    trades = (
        client.table("paper_trades")
        .select("*")
        .eq("status", "CLOSED")
        .order("closed_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return trades
