"""
Position Manager — monitors open trades and triggers closes.

Close reasons:
  TRAILING_STOP   — price dropped below trailing stop
  TAKE_PROFIT     — price hit take profit target
  TIMEOUT         — trade open > max days
  RESOLUTION      — market resolved (yes_price near 0 or 1)
  CIRCUIT_BREAKER — manual / risk-triggered close
"""

from datetime import datetime, timezone, timedelta

from src.db import supabase_client as db
from src.trading.paper_trader import close_trade
from src.trading.risk_manager import (
    get_portfolio_state,
    trigger_circuit_breaker,
    reset_consecutive_losses,
)
from src.utils.config import TRAILING_STOP_PCT, TAKE_PROFIT_PCT
from src.utils.logger import logger

MAX_TRADE_DAYS = 7
RESOLUTION_THRESHOLD = 0.97  # yes_price > 0.97 = resolved YES, < 0.03 = resolved NO


def _get_latest_price(client, market_id: str, direction: str) -> float | None:
    result = (
        client.table("market_snapshots")
        .select("yes_price")
        .eq("market_id", market_id)
        .not_.is_("yes_price", "null")
        .order("snapshot_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    yes_price = float(result.data[0]["yes_price"])
    # For NO trades, flip the price perspective
    return yes_price if direction == "YES" else round(1 - yes_price, 4)


def _is_expired(trade: dict) -> bool:
    opened_at = trade.get("opened_at", "")
    if not opened_at:
        return False
    try:
        dt = datetime.fromisoformat(opened_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(tz=timezone.utc) > dt + timedelta(days=MAX_TRADE_DAYS)
    except Exception:
        return False


def _is_resolved(yes_price: float) -> tuple[bool, float | None]:
    """
    Returns (is_resolved, yes_exit_price).
    Detects resolution in both directions regardless of trade direction.
      yes_price >= 0.97 → market resolved YES → yes_exit = 1.0
      yes_price <= 0.03 → market resolved NO  → yes_exit = 0.0
    """
    if yes_price >= RESOLUTION_THRESHOLD:
        return True, 1.0
    if yes_price <= (1 - RESOLUTION_THRESHOLD):
        return True, 0.0
    return False, None


def check_open_positions() -> int:
    """
    Check all open trades and close any that hit stop/TP/timeout/resolution.
    Returns number of trades closed.
    """
    client = db.get_client()
    state = get_portfolio_state(client)
    if not state:
        return 0

    open_trades = (
        client.table("paper_trades")
        .select("*")
        .eq("status", "OPEN")
        .execute()
        .data
    )

    if not open_trades:
        return 0

    closed = 0
    for trade in open_trades:
        market_id = trade["market_id"]
        direction = trade["direction"]
        entry_price = float(trade["entry_price"])

        current_price = _get_latest_price(client, market_id, direction)
        if current_price is None:
            logger.debug(f"No price for trade {trade['id'][:8]}... — skipping")
            continue

        close_reason = None

        # 1. Market resolution — check before stop/TP to avoid misclassification
        # A price near 0 or 1 means the market resolved, not a trailing stop
        raw_yes = _get_latest_price(client, market_id, "YES")
        if raw_yes is not None:
            resolved, yes_exit = _is_resolved(raw_yes)
            if resolved:
                # Convert yes_exit to the trade's perspective
                exit_price = yes_exit if direction == "YES" else round(1 - yes_exit, 4)
                close_reason = "RESOLUTION"
                current_price = exit_price

        # 2-4. Only check if not already resolved
        if close_reason is None:
            # 2. Timeout
            if _is_expired(trade):
                close_reason = "TIMEOUT"

            # 3. Trailing stop
            elif current_price <= entry_price * (1 - TRAILING_STOP_PCT):
                close_reason = "TRAILING_STOP"

            # 4. Take profit
            elif current_price >= entry_price * (1 + TAKE_PROFIT_PCT):
                close_reason = "TAKE_PROFIT"

        if close_reason:
            result = close_trade(trade, current_price, close_reason)
            if result:
                closed += 1
                # Update circuit breaker state
                pnl = (current_price - entry_price) * float(trade["shares"])
                state = get_portfolio_state(client)  # refresh state
                if pnl < 0:
                    trigger_circuit_breaker(client, state)
                else:
                    reset_consecutive_losses(client, state)

    if closed:
        logger.info(f"Position manager: closed {closed} trade(s)")

    return closed
