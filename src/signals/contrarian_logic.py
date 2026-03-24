"""
Contrarian logic — combines component scores into a final signal decision.

Score breakdown:
  Divergence score  × 0.50  (whale herding + price velocity)
  Momentum score    × 0.30  (pattern quality)
  Smart wallet score× 0.20  (watched wallets alignment — simplified v1)

If total ≥ SIGNAL_THRESHOLD → generate signal.
"""

from src.utils.config import (
    WEIGHT_DIVERGENCE,
    WEIGHT_MOMENTUM,
    WEIGHT_SMART_WALLET,
    SIGNAL_THRESHOLD,
)


def get_smart_wallet_score(db_client) -> float:
    """
    v1 proxy: how many tier-S/A smart wallets do we have tracked?
    Phase 3 will replace this with real-time wallet activity per market.
    """
    try:
        s_count = len(db_client.table("watched_wallets").select("id").eq("is_active", True).eq("tier", "S").execute().data)
        a_count = len(db_client.table("watched_wallets").select("id").eq("is_active", True).eq("tier", "A").execute().data)
        tracked = s_count + a_count
        if tracked >= 5:
            return 50.0
        if tracked >= 1:
            return 35.0
        return 20.0
    except Exception:
        return 20.0


def calculate_total_score(
    divergence_score: float,
    momentum_score: float,
    smart_wallet_score: float,
) -> float:
    return round(
        divergence_score * WEIGHT_DIVERGENCE
        + momentum_score * WEIGHT_MOMENTUM
        + smart_wallet_score * WEIGHT_SMART_WALLET,
        2,
    )


def should_generate_signal(
    divergence_score: float,
    momentum_score: float,
    smart_wallet_score: float,
    momentum_tradeable: bool,
    divergence_detected: bool,
) -> tuple[bool, float]:
    """
    Returns (generate: bool, total_score: float).
    Both conditions must be true: divergence detected AND momentum tradeable.
    """
    if not divergence_detected or not momentum_tradeable:
        return False, 0.0

    total = calculate_total_score(divergence_score, momentum_score, smart_wallet_score)
    return total >= SIGNAL_THRESHOLD, total


def estimate_edge(price: float, direction: str) -> float:
    """
    Rough mean-reversion edge estimate for Kelly sizing.
    Assumes fair value is ~0.5 for binary markets.
    """
    if price is None:
        return 0.05
    if direction == "YES":
        return max(0.05, min(0.40, 0.5 - price))
    else:
        return max(0.05, min(0.40, price - 0.5))
