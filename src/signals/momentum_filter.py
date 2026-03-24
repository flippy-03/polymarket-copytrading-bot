"""
Momentum filter — classifies price movement pattern to decide
whether to take a contrarian position.

Patterns:
  TREND          → 1h and 4h going same direction, strong → skip (fighting trend)
  SPIKE_REVERSAL → big 1h move, 4h flat/opposite → high-confidence contrarian
  REVERSAL       → 1h and 4h opposite directions → moderate contrarian
  WEAK_TREND     → small move, unclear → skip
  FLAT           → no movement → skip
"""


def calculate_momentum_score(velocity_1h: float, velocity_4h: float) -> dict:
    """
    Returns:
      score      : 0-100 (higher = more favorable for contrarian)
      pattern    : str label
      tradeable  : bool (False = skip this market)
    """
    if abs(velocity_1h) < 0.002:  # less than 0.2% = flat
        return {"score": 0.0, "pattern": "FLAT", "tradeable": False}

    same_direction = (velocity_1h > 0) == (velocity_4h > 0)

    # Strong trend: both timeframes aligned and 4h move > 3%
    if same_direction and abs(velocity_4h) > 0.03:
        # Bad for contrarian — the longer-term momentum is too strong
        score = max(0.0, 25.0 - abs(velocity_4h) * 200)
        return {"score": round(score, 2), "pattern": "TREND", "tradeable": False}

    # Spike: rapid 1h move (≥5%) with no strong 4h backing = likely overshoot
    if abs(velocity_1h) >= 0.05:
        if not same_direction or abs(velocity_4h) < 0.02:
            score = min(100.0, abs(velocity_1h) * 600)  # 5% → 30pts, 17% → 100pts
            return {"score": round(score, 2), "pattern": "SPIKE_REVERSAL", "tradeable": True}

    # Reversal: 1h and 4h go opposite directions
    if not same_direction and abs(velocity_1h) >= 0.02:
        score = min(80.0, abs(velocity_1h) * 300)
        return {"score": round(score, 2), "pattern": "REVERSAL", "tradeable": True}

    # Everything else: weak or unclear
    return {"score": 20.0, "pattern": "WEAK_TREND", "tradeable": False}
