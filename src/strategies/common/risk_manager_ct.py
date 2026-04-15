"""
Risk management shared by both strategies.
Per-strategy circuit breakers, sizing and drawdown checks operating on
portfolio_state_ct rows.
"""
from datetime import datetime, timedelta, timezone

from src.strategies.common import config as C
from src.strategies.common import db
from src.utils.logger import logger


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def is_circuit_broken(strategy: str) -> bool:
    p = db.get_portfolio(strategy)
    if not p:
        return False
    if not p.get("is_circuit_broken"):
        return False
    until = p.get("circuit_broken_until")
    if until and datetime.fromisoformat(until.replace("Z", "+00:00")) <= _now():
        db.update_portfolio(strategy, {"is_circuit_broken": False, "circuit_broken_until": None})
        return False
    return True


def current_drawdown(strategy: str) -> float:
    p = db.get_portfolio(strategy)
    if not p:
        return 0.0
    initial = float(p["initial_capital"])
    current = float(p["current_capital"])
    if initial <= 0:
        return 0.0
    return max(0.0, (initial - current) / initial)


def can_open_position(strategy: str) -> tuple[bool, str]:
    if is_circuit_broken(strategy):
        return False, "circuit_breaker_active"
    if current_drawdown(strategy) >= C.MAX_DRAWDOWN_PCT:
        return False, f"drawdown>={C.MAX_DRAWDOWN_PCT:.0%}"

    p = db.get_portfolio(strategy)
    if not p:
        return False, "no_portfolio_row"
    open_positions = int(p.get("open_positions") or 0)
    max_positions = int(p.get("max_open_positions") or C.MAX_OPEN_POSITIONS)
    if open_positions >= max_positions:
        return False, f"open_positions={open_positions}>={max_positions}"

    return True, "ok"


def position_size(strategy: str, max_pct: float = C.MAX_PER_TRADE_PCT) -> float:
    p = db.get_portfolio(strategy)
    if not p:
        return 0.0
    return round(float(p["current_capital"]) * max_pct, 2)


def register_loss_and_maybe_break(strategy: str, loss_pct: float) -> None:
    p = db.get_portfolio(strategy)
    if not p:
        return
    if loss_pct >= -0.02:
        db.update_portfolio(strategy, {"consecutive_losses": 0})
        return
    losses = int(p.get("consecutive_losses") or 0) + 1
    data: dict = {"consecutive_losses": losses}
    if losses >= 3:
        until = (_now() + timedelta(hours=12)).isoformat()
        data["is_circuit_broken"] = True
        data["circuit_broken_until"] = until
        logger.warning(f"[{strategy}] Circuit breaker tripped until {until}")
    db.update_portfolio(strategy, data)
