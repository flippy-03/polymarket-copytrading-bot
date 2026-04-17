"""
Cooldown / hysteresis manager for Scalper V2.

When a titular is removed for underperformance, a cooldown is set on the
(wallet, market_type) pair to prevent immediate re-selection.

Escalation:
  1st removal: 30 days
  2nd removal of same pair: 60 days
  3rd+: 90 days

After cooldown expires, the wallet is eligible again only if its
composite_score >= 0.50 for that market type.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.strategies.common import config as C, db
from src.strategies.scalper.pool_selector import _composite_score
from src.utils.logger import logger

_COOLDOWN_DAYS = {1: 30, 2: 60, 3: 90}


def add_cooldown(
    wallet: str,
    market_type: str,
    reason: str,
    metrics_snapshot: dict | None = None,
) -> None:
    """Add a cooldown for a (wallet, market_type) pair with escalation."""
    previous_count = db.count_cooldown_history(wallet, market_type)
    level = min(3, previous_count + 1)
    days = _COOLDOWN_DAYS.get(level, C.SCALPER_COOLDOWN_DAYS_BASE)

    expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()

    db.insert_cooldown(
        wallet=wallet,
        market_type=market_type,
        reason=reason,
        expires_at=expires_at,
        escalation_level=level,
        metrics_at_removal=metrics_snapshot,
    )
    logger.info(
        f"  cooldown: {wallet[:10]}… / {market_type} → "
        f"{days}d (level {level}, reason={reason})"
    )


def check_cooldown_eligible(
    wallet: str,
    market_type: str,
    wallet_profile: dict | None = None,
) -> bool:
    """Check if a previously cooled-down wallet is eligible again.

    Returns True if no active cooldown or if cooldown expired AND metrics
    recovered (composite_score >= 0.50).
    """
    cooldown = db.get_active_cooldown(wallet, market_type)
    if not cooldown:
        return True

    expires = cooldown.get("expires_at", "")
    if isinstance(expires, str):
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
    else:
        return False

    now = datetime.now(tz=timezone.utc)
    if exp_dt > now:
        return False  # still in cooldown

    # Cooldown expired — check if metrics recovered
    if wallet_profile:
        type_hrs = wallet_profile.get("type_hit_rates") or {}
        type_pfs = wallet_profile.get("type_profit_factors") or {}
        type_tcs = wallet_profile.get("type_trade_counts") or {}
        type_sharpes = wallet_profile.get("type_sharpe_ratios") or {}

        score = _composite_score(
            type_hr=type_hrs.get(market_type, 0),
            type_pf=type_pfs.get(market_type, 0),
            type_tc=type_tcs.get(market_type, 0),
            type_sharpe=type_sharpes.get(market_type, 0),
            worst_30d_hr=wallet_profile.get("worst_30d_hit_rate") or 0,
            hr_variance=wallet_profile.get("hit_rate_variance") or 0.15,
            momentum=wallet_profile.get("momentum_score") or 0,
            sharpe_proxy=wallet_profile.get("sharpe_proxy") or 0,
            confidence=wallet_profile.get("profile_confidence") or "LOW",
            is_priority=False,
        )
        if score < 0.50:
            logger.debug(
                f"  cooldown expired but score={score:.3f} < 0.50 for "
                f"{wallet[:10]}… / {market_type} — extending"
            )
            return False

    # Metrics recovered (or no profile to check) — deactivate cooldown
    db.deactivate_cooldown(cooldown["id"])
    logger.info(f"  cooldown cleared: {wallet[:10]}… / {market_type}")
    return True


def list_active() -> list[dict]:
    """Return all active cooldowns (for dashboard display)."""
    return db.list_active_cooldowns()
