"""
Signal generator — classify MarketAnalysis into CLEAN / CONTESTED / SKIP signals.

Signal quality (spec §8):
  CLEAN     = dominant_count / opposition_count >= SIGNAL_CLEAN_RATIO (2.5)
              AND at least SIGNAL_MIN_SPECIALISTS on the winning side
  CONTESTED = ratio >= SIGNAL_CONTESTED_RATIO (1.5)
  SKIP      = ratio < 1.5 OR no specialists on any side

Expected ROI:
  Potential ROI = (1 / price) - 1 for the winning side
  Adjusted for signal quality and conflict penalty.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.strategies.common import config as C
from src.strategies.specialist.specialist_analyzer import MarketAnalysis, SideAnalysis


class SignalQuality(str, Enum):
    CLEAN = "CLEAN"
    CONTESTED = "CONTESTED"
    SKIP = "SKIP"


@dataclass
class Signal:
    market: dict
    universe: str
    market_type: str
    direction: str         # "YES" or "NO"
    quality: SignalQuality
    specialists_for: int
    specialists_against: int
    ratio: float
    avg_specialist_score: float
    avg_hit_rate: float
    entry_price: float
    potential_roi: float
    confidence: float
    conflict_penalty: float
    expected_roi: float
    condition_id: str

    @property
    def is_actionable(self) -> bool:
        return self.quality in (SignalQuality.CLEAN, SignalQuality.CONTESTED)


def _get_price(market: dict, direction: str) -> float:
    """Extract current price for YES or NO from market data.

    Gamma API dicts have outcomePrices/lastTradePrice, not a 'tokens' list.
    We try both formats.
    """
    # Format A: tokens list (if present)
    tokens = market.get("tokens") or []
    for tok in tokens:
        outcome = (tok.get("outcome") or "").upper()
        if outcome == direction:
            p = tok.get("price") or tok.get("lastTradePrice") or tok.get("bestAsk")
            try:
                return float(p)
            except (TypeError, ValueError):
                pass

    # Format B: Gamma outcomePrices = [yes_price, no_price]
    idx = 0 if direction == "YES" else 1
    p_list = market.get("outcomePrices") or market.get("prices")
    if isinstance(p_list, list) and len(p_list) > idx:
        try:
            return float(p_list[idx])
        except (TypeError, ValueError):
            pass

    # Format C: lastTradePrice (single value — treat as YES price)
    if direction == "YES":
        ltp = market.get("lastTradePrice")
        if ltp:
            try:
                return float(ltp)
            except (TypeError, ValueError):
                pass

    return 0.5  # Unknown price


def generate_signal(analysis: MarketAnalysis) -> Optional[Signal]:
    """
    Generate a Signal from a MarketAnalysis, or None if SKIP.
    """
    yes = analysis.yes_side
    no = analysis.no_side

    if yes.count == 0 and no.count == 0:
        return _skip(analysis, "no_specialists")

    # Determine dominant vs opposition
    if yes.count >= no.count and yes.count > 0:
        dominant = yes
        opposition = no
    elif no.count > yes.count:
        dominant = no
        opposition = yes
    else:
        # Tie in count — use avg_score as tiebreaker
        if yes.avg_score >= no.avg_score:
            dominant = yes
            opposition = no
        else:
            dominant = no
            opposition = yes

    if dominant.count < C.SIGNAL_MIN_SPECIALISTS:
        return _skip(analysis, "too_few_specialists")

    # Conflict ratio
    if opposition.count > 0:
        ratio = dominant.count / opposition.count
        conflict_penalty = C.SIGNAL_CONFLICT_PENALTY
    else:
        # Uncontested — cap at 2×CLEAN threshold so the signal is always CLEAN
        ratio = C.SIGNAL_CLEAN_RATIO * 2
        conflict_penalty = 0.0

    # Quality classification
    if ratio >= C.SIGNAL_CLEAN_RATIO:
        quality = SignalQuality.CLEAN
    elif ratio >= C.SIGNAL_CONTESTED_RATIO:
        quality = SignalQuality.CONTESTED
    else:
        return _skip(analysis, f"low_ratio={ratio:.1f}")

    direction = dominant.side
    entry_price = _get_price(analysis.market, direction)

    # Price guard: avoid near-certain markets
    if entry_price < C.SPECIALIST_MARKET_MIN_PRICE or entry_price > C.SPECIALIST_MARKET_MAX_PRICE:
        return _skip(analysis, f"price_out_of_range={entry_price:.2f}")

    if entry_price <= 0:
        return _skip(analysis, "zero_price")

    potential_roi = (1.0 / entry_price) - 1.0

    # Confidence based on quality
    if quality == SignalQuality.CLEAN:
        confidence = min(0.7 + dominant.avg_hit_rate * 0.3, 0.95)
    else:
        confidence = min(0.5 + dominant.avg_hit_rate * 0.2, 0.75)

    expected_roi = potential_roi * confidence * (1.0 - conflict_penalty)

    return Signal(
        market=analysis.market,
        universe=analysis.universe,
        market_type=analysis.market_type,
        direction=direction,
        quality=quality,
        specialists_for=dominant.count,
        specialists_against=opposition.count,
        ratio=round(ratio, 2),
        avg_specialist_score=round(dominant.avg_score, 4),
        avg_hit_rate=round(dominant.avg_hit_rate, 4),
        entry_price=round(entry_price, 4),
        potential_roi=round(potential_roi, 4),
        confidence=round(confidence, 4),
        conflict_penalty=round(conflict_penalty, 4),
        expected_roi=round(expected_roi, 4),
        condition_id=analysis.condition_id,
    )


def _skip(analysis: MarketAnalysis, reason: str) -> None:
    from src.utils.logger import logger
    logger.debug(
        f"  signal SKIP {analysis.condition_id[:12]}… reason={reason}"
    )
    return None
