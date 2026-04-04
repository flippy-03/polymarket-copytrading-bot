"""
Position Manager — monitors open trades and triggers closes.

Close reasons:
  TRAILING_STOP   — price dropped below trailing stop
  TAKE_PROFIT     — price hit take profit target
  TIMEOUT         — trade open > max days
  RESOLUTION      — market resolved (yes_price near 0 or 1)
  CIRCUIT_BREAKER — manual / risk-triggered close
"""

import json
import urllib.request
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

MAX_TRADE_DAYS = 3
STALE_POSITION_HOURS = 48    # close lateralized positions after this many hours
STALE_PNL_THRESHOLD = 0.10   # position is "lateral" if |pnl_pct| < this
RESOLUTION_THRESHOLD = 0.97  # yes_price > 0.97 = resolved YES, < 0.03 = resolved NO
STALE_SNAPSHOT_HOURS = 3     # fallback to Gamma API if snapshot is older than this


def _fetch_yes_price_gamma(client, market_id: str) -> float | None:
    """Fetch current yes_price directly from Gamma API as fallback for stale snapshots."""
    try:
        market = (
            client.table("markets")
            .select("polymarket_id")
            .eq("id", market_id)
            .execute()
            .data
        )
        if not market or not market[0].get("polymarket_id"):
            return None
        polymarket_id = market[0]["polymarket_id"]
        url = f"https://gamma-api.polymarket.com/markets/{polymarket_id}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        prices = data.get("outcomePrices")
        if prices and len(prices) >= 1:
            return float(prices[0])  # prices[0] = YES
        return None
    except Exception as e:
        logger.warning(f"Gamma API fallback failed for market {market_id[:8]}...: {e}")
        return None


def _get_latest_price(client, market_id: str, direction: str) -> float | None:
    result = (
        client.table("market_snapshots")
        .select("yes_price, snapshot_at")
        .eq("market_id", market_id)
        .not_.is_("yes_price", "null")
        .order("snapshot_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        snap = result.data[0]
        snap_dt = datetime.fromisoformat(snap["snapshot_at"])
        if snap_dt.tzinfo is None:
            snap_dt = snap_dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(tz=timezone.utc) - snap_dt).total_seconds() / 3600
        if age_hours <= STALE_SNAPSHOT_HOURS:
            yes_price = float(snap["yes_price"])
            return yes_price if direction == "YES" else round(1 - yes_price, 4)
        logger.warning(
            f"Snapshot for {market_id[:8]}... is {age_hours:.1f}h old — "
            f"falling back to Gamma API"
        )

    # Fallback: snapshot missing or stale → query Gamma API directly
    yes_price = _fetch_yes_price_gamma(client, market_id)
    if yes_price is None:
        return None
    logger.info(f"Gamma API fallback price for {market_id[:8]}...: YES={yes_price:.3f}")
    return yes_price if direction == "YES" else round(1 - yes_price, 4)


def _is_stale(trade: dict, current_price: float) -> bool:
    """
    A position is stale if it's been open >STALE_POSITION_HOURS and the P&L
    is lateralized (between -STALE_PNL_THRESHOLD and +STALE_PNL_THRESHOLD).
    These positions occupy a slot without any edge — better to free it.
    """
    opened_at = trade.get("opened_at", "")
    if not opened_at:
        return False
    try:
        dt = datetime.fromisoformat(opened_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours_open = (datetime.now(tz=timezone.utc) - dt).total_seconds() / 3600
        if hours_open < STALE_POSITION_HOURS:
            return False
    except Exception:
        return False

    entry_price = float(trade["entry_price"])
    if entry_price <= 0:
        return False
    pnl_pct = abs((current_price - entry_price) / entry_price)
    return pnl_pct < STALE_PNL_THRESHOLD


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

        # 2-5. Only check if not already resolved
        if close_reason is None:
            # 2. Timeout
            if _is_expired(trade):
                close_reason = "TIMEOUT"

            # 3. Stale position: open >48h with P&L between -10% and +10%
            #    Not moving = no edge, just blocking a slot for better signals.
            elif _is_stale(trade, current_price):
                close_reason = "STALE"

            # 4. Trailing stop
            elif current_price <= entry_price * (1 - TRAILING_STOP_PCT):
                close_reason = "TRAILING_STOP"

            # 5. Take profit
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


def check_shadow_positions() -> int:
    """
    Check all OPEN shadow trades and close those that hit stop/TP/timeout/resolution.
    Mirror of check_open_positions() but operates on shadow_trades table.
    No circuit breaker or portfolio updates — shadow trades are read-only for risk.
    Returns number of shadow trades closed.
    """
    client = db.get_client()

    shadow_trades = (
        client.table("shadow_trades")
        .select("*")
        .eq("status", "OPEN")
        .execute()
        .data
    )

    if not shadow_trades:
        return 0

    closed = 0
    now = datetime.now(tz=timezone.utc).isoformat()

    for trade in shadow_trades:
        market_id = trade["market_id"]
        direction = trade["direction"]
        entry_price = float(trade["entry_price"])

        current_price = _get_latest_price(client, market_id, direction)
        if current_price is None:
            continue

        close_reason = None

        # 1. Resolution
        raw_yes = _get_latest_price(client, market_id, "YES")
        if raw_yes is not None:
            resolved, yes_exit = _is_resolved(raw_yes)
            if resolved:
                exit_price = yes_exit if direction == "YES" else round(1 - yes_exit, 4)
                close_reason = "RESOLUTION"
                current_price = exit_price

        if close_reason is None:
            entry_at = trade.get("entry_at", "")
            # 2. Timeout (use entry_at as trade open time)
            if entry_at:
                try:
                    dt = datetime.fromisoformat(entry_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if datetime.now(tz=timezone.utc) > dt + timedelta(days=MAX_TRADE_DAYS):
                        close_reason = "TIMEOUT"
                except Exception:
                    pass

            # 3. Trailing stop
            if close_reason is None and current_price <= entry_price * (1 - TRAILING_STOP_PCT):
                close_reason = "TRAILING_STOP"

            # 4. Take profit
            elif close_reason is None and current_price >= entry_price * (1 + TAKE_PROFIT_PCT):
                close_reason = "TAKE_PROFIT"

        if close_reason:
            shares_shadow = float(trade.get("shares") or 0)
            pos_usd_shadow = float(trade.get("position_usd") or 0)
            if shares_shadow > 0:
                pnl_usd = round((current_price - entry_price) * shares_shadow, 2)
            else:
                # Fallback for legacy rows without shares (pre-migration)
                pnl_usd = round((current_price - entry_price) / entry_price * 10, 2)
            pnl_pct = round((current_price - entry_price) / entry_price, 4) if entry_price else 0
            client.table("shadow_trades").update({
                "exit_price": current_price,
                "exit_at": now,
                "close_reason": close_reason,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "status": "CLOSED",
            }).eq("id", trade["id"]).execute()
            closed += 1
            result_str = "WIN" if pnl_usd > 0 else "LOSS"
            logger.debug(
                f"Shadow [{result_str}] {direction} {close_reason} "
                f"entry={entry_price:.3f} exit={current_price:.3f} "
                f"P&L ${pnl_usd:+.2f}"
            )

    if closed:
        logger.info(f"Shadow position manager: closed {closed} shadow trade(s)")

    return closed
