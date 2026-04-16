"""
Risk management shared by both strategies.
Per-strategy circuit breakers, sizing and drawdown checks operating on
portfolio_state_ct rows. All operations are scoped to (strategy, run_id) and
only act on the real portfolio (is_shadow=False) — shadow trades bypass risk.

Circuit breaker behaviour:
  - Triggered automatically after SCALPER_CONSECUTIVE_LOSS_LIMIT consecutive
    losses (each > 2%). Lockout = 24 h + requires_manual_review = True.
  - When requires_manual_review is True the timer can expire but the bot will
    NOT resume automatically — the operator must call manual_resume() (or click
    the dashboard "Resume" button).
  - Manual pause from dashboard also sets requires_manual_review = True.

Drawdown is measured from the portfolio's All-Time High (peak_capital), not
from initial_capital. peak_capital is updated after every real trade close.
"""
from datetime import datetime, timedelta, timezone

from src.strategies.common import config as C
from src.strategies.common import db
from src.utils.logger import logger

# Per-strategy consecutive-loss thresholds.
# Scalper = 3 (high-frequency, 3 losses is a systemic signal).
# Specialist = 5 (few positions, multi-hour horizons, 3 losses is variance).
_LOSS_STREAK_LIMITS: dict[str, int] = {
    "SCALPER": C.SCALPER_CONSECUTIVE_LOSS_LIMIT,
    "SPECIALIST": C.SPECIALIST_CONSECUTIVE_LOSS_LIMIT,
}
_DEFAULT_LOSS_STREAK_LIMIT = C.SCALPER_CONSECUTIVE_LOSS_LIMIT
_COOLDOWN_HOURS = 24


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Circuit breaker ───────────────────────────────────────────────────────────

def is_circuit_broken(strategy: str, *, run_id: str) -> bool:
    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return False
    if not p.get("is_circuit_broken"):
        return False
    # If manual review is required, NEVER auto-reset — operator must resume.
    if p.get("requires_manual_review"):
        return True
    until = p.get("circuit_broken_until")
    if until and datetime.fromisoformat(until.replace("Z", "+00:00")) <= _now():
        db.update_portfolio(
            strategy,
            {"is_circuit_broken": False, "circuit_broken_until": None},
            run_id=run_id,
        )
        return False
    return True


def register_loss_and_maybe_break(strategy: str, loss_pct: float, *, run_id: str) -> None:
    """Call after every real trade close. Resets streak on wins, trips CB on streaks."""
    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return
    # Anything better than -2% is considered a win/scratch — reset the streak.
    if loss_pct >= -0.02:
        db.update_portfolio(strategy, {"consecutive_losses": 0}, run_id=run_id)
        return
    losses = int(p.get("consecutive_losses") or 0) + 1
    data: dict = {"consecutive_losses": losses}
    limit = _LOSS_STREAK_LIMITS.get(strategy, _DEFAULT_LOSS_STREAK_LIMIT)
    if losses >= limit:
        until = (_now() + timedelta(hours=_COOLDOWN_HOURS)).isoformat()
        data["is_circuit_broken"] = True
        data["circuit_broken_until"] = until
        data["requires_manual_review"] = True
        logger.warning(
            f"[{strategy}] CIRCUIT BREAKER — {losses} consecutive losses. "
            f"Paused until {until}. MANUAL REVIEW REQUIRED before resuming."
        )
    db.update_portfolio(strategy, data, run_id=run_id)


def manual_pause(strategy: str, *, run_id: str) -> None:
    """Operator-initiated stop from dashboard. Requires explicit manual_resume()."""
    db.update_portfolio(
        strategy,
        {
            "is_circuit_broken": True,
            "circuit_broken_until": None,
            "requires_manual_review": True,
        },
        run_id=run_id,
    )
    logger.warning(f"[{strategy}] Manual stop activated — trading paused until manual resume.")


def manual_resume(strategy: str, *, run_id: str) -> None:
    """Re-enable trading after a manual stop or post-loss cooldown review."""
    db.update_portfolio(
        strategy,
        {
            "is_circuit_broken": False,
            "circuit_broken_until": None,
            "requires_manual_review": False,
            "consecutive_losses": 0,
        },
        run_id=run_id,
    )
    logger.info(f"[{strategy}] Manual resume — trading re-enabled.")


# ── Drawdown (ATH-based) ──────────────────────────────────────────────────────

def update_peak_capital(strategy: str, *, run_id: str) -> None:
    """
    Update peak_capital whenever current_capital exceeds it.
    Call after every real trade close so the high-water mark stays current.
    """
    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return
    current = float(p.get("current_capital") or 0)
    peak = float(p.get("peak_capital") or p.get("initial_capital") or 0)
    if current > peak:
        db.update_portfolio(strategy, {"peak_capital": current}, run_id=run_id)


def current_drawdown(strategy: str, *, run_id: str) -> float:
    """
    Drawdown from the portfolio's All-Time High (peak_capital).
    Returns a value in [0, 1]. 0.30 means 30% below ATH.
    """
    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return 0.0
    current = float(p.get("current_capital") or 0)
    peak = float(p.get("peak_capital") or p.get("initial_capital") or 0)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)


# ── Position gating ───────────────────────────────────────────────────────────

def can_open_position(strategy: str, *, run_id: str) -> tuple[bool, str]:
    if is_circuit_broken(strategy, run_id=run_id):
        return False, "circuit_breaker_active"
    if current_drawdown(strategy, run_id=run_id) >= C.MAX_DRAWDOWN_PCT:
        return False, f"drawdown>={C.MAX_DRAWDOWN_PCT:.0%}_from_ATH"

    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return False, "no_portfolio_row"
    open_positions = int(p.get("open_positions") or 0)
    max_positions = int(p.get("max_open_positions") or C.MAX_OPEN_POSITIONS)
    if open_positions >= max_positions:
        return False, f"open_positions={open_positions}>={max_positions}"

    return True, "ok"


def position_size(strategy: str, *, run_id: str, max_pct: float = C.MAX_PER_TRADE_PCT) -> float:
    p = db.get_portfolio(strategy, run_id=run_id)
    if not p:
        return 0.0
    return round(float(p["current_capital"]) * max_pct, 2)
