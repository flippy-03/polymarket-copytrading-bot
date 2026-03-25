"""
Risk Manager — position sizing, circuit breaker, exposure limits.
"""

from datetime import datetime, timezone

from src.utils.config import (
    INITIAL_CAPITAL,
    MAX_POSITION_SIZE_PCT,
    MAX_OPEN_POSITIONS,
    KELLY_FRACTION,
    CIRCUIT_BREAKER_LOSSES,
    CIRCUIT_BREAKER_COOLDOWN_HOURS,
    MAX_DRAWDOWN_PCT,
)
from src.utils.logger import logger


def get_portfolio_state(client) -> dict | None:
    result = client.table("portfolio_state").select("*").order("run_id", desc=True).limit(1).execute()
    return result.data[0] if result.data else None


def is_trading_allowed(state: dict) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Checks circuit breaker, max drawdown, max open positions.
    """
    if state.get("is_circuit_broken"):
        broken_until = state.get("circuit_broken_until")
        if broken_until:
            now = datetime.now(tz=timezone.utc)
            until_dt = datetime.fromisoformat(broken_until)
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=timezone.utc)
            if now < until_dt:
                return False, f"circuit_breaker (until {broken_until[:16]})"

    open_pos = state.get("open_positions", 0)
    if open_pos >= MAX_OPEN_POSITIONS:
        return False, f"max_open_positions ({open_pos}/{MAX_OPEN_POSITIONS})"

    current = float(state.get("current_capital", INITIAL_CAPITAL))
    initial = float(state.get("initial_capital", INITIAL_CAPITAL))
    drawdown = (initial - current) / initial if initial > 0 else 0
    if drawdown >= MAX_DRAWDOWN_PCT:
        return False, f"max_drawdown ({drawdown:.1%})"

    return True, "ok"


def kelly_position_size(
    edge: float,
    odds: float,
    capital: float,
) -> float:
    """
    Half-Kelly position sizing.
    edge: estimated win probability (0-1)
    odds: payout multiplier (e.g. 1/entry_price - 1)
    capital: available capital in USD
    Returns position size in USD.
    """
    if odds <= 0 or edge <= 0:
        return 0.0

    kelly_full = (edge * odds - (1 - edge)) / odds
    kelly_half = kelly_full * KELLY_FRACTION

    if kelly_half <= 0:
        return 0.0

    raw = kelly_half * capital
    max_size = capital * MAX_POSITION_SIZE_PCT
    return round(min(raw, max_size), 2)


def trigger_circuit_breaker(client, state: dict) -> None:
    from datetime import timedelta

    losses = state.get("consecutive_losses", 0) + 1
    if losses >= CIRCUIT_BREAKER_LOSSES:
        until = datetime.now(tz=timezone.utc) + timedelta(hours=CIRCUIT_BREAKER_COOLDOWN_HOURS)
        client.table("portfolio_state").update({
            "consecutive_losses": losses,
            "is_circuit_broken": True,
            "circuit_broken_until": until.isoformat(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }).eq("id", state["id"]).execute()
        logger.warning(f"CIRCUIT BREAKER triggered — pausing until {until.strftime('%Y-%m-%d %H:%M')} UTC")
    else:
        client.table("portfolio_state").update({
            "consecutive_losses": losses,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }).eq("id", state["id"]).execute()


def reset_consecutive_losses(client, state: dict) -> None:
    client.table("portfolio_state").update({
        "consecutive_losses": 0,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("id", state["id"]).execute()
