"""
Paper Trader — opens and closes simulated trades based on signals.
"""

from datetime import datetime, timezone, timedelta

from src.db import supabase_client as db
from src.trading.risk_manager import (
    get_portfolio_state,
    is_trading_allowed,
    kelly_position_size,
)
from src.utils.config import (
    TRAILING_STOP_PCT,
    TAKE_PROFIT_PCT,
    MAX_SIGNAL_DRIFT_PCT,
    MIN_CONTRARIAN_PRICE,
)
from src.utils.logger import logger

# Reasons that reflect execution CAPACITY, not signal quality.
# Shadow trades are only opened when blocked for these reasons.
_CAPACITY_BLOCK_REASONS = {"max_open_positions", "circuit_breaker", "max_drawdown"}


def _get_current_price(market_id: str) -> float | None:
    """Fetch latest yes_price from market_snapshots."""
    client = db.get_client()
    result = (
        client.table("market_snapshots")
        .select("yes_price")
        .eq("market_id", market_id)
        .not_.is_("yes_price", "null")
        .order("snapshot_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return float(result.data[0]["yes_price"])
    return None


def open_trade(signal: dict) -> dict | None:
    """
    Open a paper trade from a signal.
    Returns the created trade row or None if not allowed.
    """
    client = db.get_client()
    state = get_portfolio_state(client)
    if not state:
        logger.error("No portfolio state found — run setup_db.py first")
        return None

    allowed, reason = is_trading_allowed(state)
    if not allowed:
        logger.info(f"Trade blocked: {reason}")
        return None

    market_id = signal["market_id"]
    direction = signal["direction"]  # YES | NO

    # Use price at signal time — reflects what would have been traded in production
    # (in production the trader runs 24/7 so signal and trade happen within seconds)
    yes_price = float(signal["price_at_signal"])
    if direction == "NO":
        entry_price = round(1 - yes_price, 4)
    else:
        entry_price = round(yes_price, 4)

    if entry_price <= 0 or entry_price >= 1:
        logger.warning(f"Invalid entry price {entry_price} for {direction} — skipping")
        return None

    # Validate current market conditions — signal may be stale
    current_yes = _get_current_price(market_id)
    if current_yes is not None:
        # 1. Market already resolved
        if current_yes >= 0.97 or current_yes <= 0.03:
            logger.info(f"Trade blocked: market resolved (yes={current_yes:.3f}) — marking signal EXPIRED")
            client.table("signals").update({"status": "EXPIRED"}).eq("id", signal["id"]).execute()
            return None
        # 2. Price drifted too far — original divergence hypothesis no longer valid
        current_entry = current_yes if direction == "YES" else round(1 - current_yes, 4)
        drift = abs(current_entry - entry_price) / entry_price
        if drift > MAX_SIGNAL_DRIFT_PCT:
            logger.info(f"Trade blocked: price drifted {drift:.0%} from signal (signal={entry_price:.3f} now={current_entry:.3f}) — marking signal EXPIRED")
            client.table("signals").update({"status": "EXPIRED"}).eq("id", signal["id"]).execute()
            return None

    # Kelly sizing: edge = confidence, odds = payout ratio
    capital = float(state["current_capital"])
    confidence = float(signal.get("confidence") or 0.55)
    odds = (1 / entry_price) - 1
    position_usd = kelly_position_size(confidence, odds, capital)

    if position_usd < 1.0:
        logger.info(f"Position too small (${position_usd:.2f}) — skipping trade")
        return None

    shares = round(position_usd / entry_price, 2)

    # Trailing stop and take profit levels
    trailing_stop = round(entry_price * (1 - TRAILING_STOP_PCT), 4)
    take_profit = round(entry_price * (1 + TAKE_PROFIT_PCT), 4)

    # Expires in 7 days (or at market resolution)
    expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=7)).isoformat()

    trade_row = {
        "signal_id": signal["id"],
        "market_id": market_id,
        "direction": direction,
        "entry_price": entry_price,
        "shares": shares,
        "position_usd": position_usd,
        "status": "OPEN",
        "opened_at": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": state["run_id"],
    }

    result = client.table("paper_trades").insert(trade_row).execute()
    if not result.data:
        logger.error("Failed to insert paper trade")
        return None

    trade = result.data[0]

    # Update portfolio: deduct capital, increment open positions
    new_capital = round(capital - position_usd, 2)
    client.table("portfolio_state").update({
        "current_capital": new_capital,
        "open_positions": state.get("open_positions", 0) + 1,
        "total_trades": state.get("total_trades", 0) + 1,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("id", state["id"]).execute()

    logger.info(
        f"TRADE OPENED | {direction} @ {entry_price:.3f} | "
        f"${position_usd:.2f} ({shares} shares) | "
        f"stop={trailing_stop:.3f} tp={take_profit:.3f}"
    )

    # Mark signal as EXECUTED
    client.table("signals").update({"status": "EXECUTED"}).eq("id", signal["id"]).execute()

    return trade


def close_trade(trade: dict, exit_price: float, reason: str) -> dict | None:
    """
    Close an open paper trade. Calculates P&L and updates portfolio.
    """
    client = db.get_client()
    state = get_portfolio_state(client)
    if not state:
        return None

    entry_price = float(trade["entry_price"])
    shares = float(trade["shares"])
    position_usd = float(trade["position_usd"])
    direction = trade["direction"]

    # P&L calculation
    if direction == "YES":
        pnl_usd = round((exit_price - entry_price) * shares, 2)
    else:
        # For NO trades: we bought NO at (1 - yes_price), profit if yes_price drops
        pnl_usd = round((exit_price - entry_price) * shares, 2)

    pnl_pct = round(pnl_usd / position_usd, 4) if position_usd > 0 else 0

    now = datetime.now(tz=timezone.utc).isoformat()
    client.table("paper_trades").update({
        "exit_price": exit_price,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "close_reason": reason,
        "closed_at": now,
        "status": "CLOSED",
    }).eq("id", trade["id"]).execute()

    # Update portfolio capital and stats
    returned_capital = position_usd + pnl_usd
    new_capital = round(float(state["current_capital"]) + returned_capital, 2)
    total_pnl = round(float(state.get("total_pnl", 0)) + pnl_usd, 2)
    initial = float(state.get("initial_capital", 1000))
    total_pnl_pct = round((new_capital - initial) / initial, 4)

    winning = state.get("winning_trades", 0) + (1 if pnl_usd > 0 else 0)
    losing = state.get("losing_trades", 0) + (1 if pnl_usd <= 0 else 0)
    total = state.get("total_trades", 1)
    win_rate = round(winning / total, 4) if total > 0 else 0

    open_pos = max(0, state.get("open_positions", 1) - 1)
    max_dd = state.get("max_drawdown", 0)
    current_dd = round((initial - new_capital) / initial, 4) if new_capital < initial else 0
    max_dd = max(float(max_dd), current_dd)

    client.table("portfolio_state").update({
        "current_capital": new_capital,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "open_positions": open_pos,
        "updated_at": now,
    }).eq("id", state["id"]).execute()

    result_str = "WIN" if pnl_usd > 0 else "LOSS"
    logger.info(
        f"TRADE CLOSED [{result_str}] | {direction} | {reason} | "
        f"entry={entry_price:.3f} exit={exit_price:.3f} | "
        f"P&L ${pnl_usd:+.2f} ({pnl_pct:+.1%})"
    )

    return trade


def open_shadow_trade(signal: dict, blocked_reason: str) -> bool:
    """
    Record a shadow trade for a signal that was blocked by capacity constraints
    (MAX_OPEN_POSITIONS, circuit_breaker, max_drawdown) — not by signal quality.

    Shadow trades track what the strategy WOULD have done, enabling signal quality
    validation independent of portfolio state.

    Returns True if a new shadow trade was created.
    """
    # Only open shadows for capacity blocks, not quality rejects
    reason_key = blocked_reason.split(" ")[0].lower()
    if not any(reason_key.startswith(k.split("_")[0]) for k in _CAPACITY_BLOCK_REASONS):
        return False

    direction = signal["direction"]
    yes_price = float(signal["price_at_signal"])
    entry_price = yes_price if direction == "YES" else round(1 - yes_price, 4)

    # Skip if entry is outside the valid contrarian range — signal engine should
    # have filtered these, but guard against legacy signals in DB.
    if entry_price < MIN_CONTRARIAN_PRICE or entry_price > (1 - MIN_CONTRARIAN_PRICE):
        return False

    client = db.get_client()

    # Avoid duplicate shadow trades for the same signal
    existing = (
        client.table("shadow_trades")
        .select("id")
        .eq("signal_id", signal["id"])
        .execute()
        .data
    )
    if existing:
        return False

    state = get_portfolio_state(client)

    # Calculate real Kelly sizing so P&L reflects actual would-be exposure
    capital = float(state["current_capital"]) if state else 1000.0
    confidence = float(signal.get("confidence") or 0.55)
    position_usd = kelly_position_size(confidence, (1 / entry_price) - 1, capital)
    shares = round(position_usd / entry_price, 4) if entry_price > 0 else 0

    shadow = {
        "signal_id": signal["id"],
        "market_id": signal["market_id"],
        "direction": direction,
        "entry_price": entry_price,
        "entry_at": datetime.now(tz=timezone.utc).isoformat(),
        "blocked_reason": blocked_reason,
        "position_usd": position_usd,
        "shares": shares,
        "status": "OPEN",
        "run_id": state["run_id"] if state else None,
    }
    client.table("shadow_trades").insert(shadow).execute()
    logger.debug(
        f"Shadow trade opened: {direction} @ {entry_price:.3f} "
        f"${position_usd:.2f} (blocked: {blocked_reason})"
    )
    return True
