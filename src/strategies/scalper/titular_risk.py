"""
Per-titular risk configuration for Scalper V2.

Derives individual circuit breaker thresholds from each trader's enriched
profile metrics. Traders with higher hit rates get tighter loss limits
(fewer consecutive losses before pause) because a long streak against their
HR is statistically more surprising.

Formula: loss_limit = ceil(-2 / log10(1 - HR)), clamped to [2, 5].
  HR=0.55 → limit 5  (streak of 5 has ~1.8% probability)
  HR=0.60 → limit 4  (streak of 4 has ~2.6% probability)
  HR=0.65 → limit 4  (streak of 4 has ~1.5% probability)
  HR=0.70 → limit 3  (streak of 3 has ~2.7% probability)
"""
from __future__ import annotations

import math

from src.strategies.common import config as C


def compute_risk_config(wallet_profile: dict) -> dict:
    """Compute per-titular risk parameters from an enriched wallet profile.

    Returns:
        {
            "per_trader_loss_limit": int,
            "per_trader_max_open": int,   # informational (not enforced; capital is the gate)
            "allocation_pct": float,
        }
    """
    hr = float(wallet_profile.get("best_type_hit_rate") or 0.55)
    hr = max(0.01, min(0.99, hr))  # clamp to avoid log(0)

    # Expected streak threshold at ~2% probability
    loss_limit = math.ceil(-2 / math.log10(1 - hr))
    loss_limit = max(2, min(5, loss_limit))

    # Informational max open (based on their typical simultaneous positions)
    typical = float(wallet_profile.get("typical_n_simultaneous") or 3)
    max_open = min(
        max(2, int(typical * 0.8)),
        C.SCALPER_MAX_OPEN_POSITIONS // C.SCALPER_ACTIVE_WALLETS,
    )

    return {
        "per_trader_loss_limit": loss_limit,
        "per_trader_max_open": max_open,
        "allocation_pct": round(1.0 / C.SCALPER_ACTIVE_WALLETS, 4),
    }
