"""
Trade executor — size + execute a Signal via clob_exec (paper mode).

Sizing (spec §11):
  size = universe_capital(universe) * SPECIALIST_TRADE_PCT
  Capped at SPECIALIST_MAX_TRADE_USD, floored at SPECIALIST_MIN_TRADE_USD.

universe_capital = total_capital * UNIVERSES[universe].capital_pct
"""
from __future__ import annotations

import json
from typing import Optional

from src.strategies.common import config as C
from src.strategies.common import clob_exec
from src.strategies.specialist.signal_generator import Signal
from src.strategies.specialist.universe_config import universe_capital
from src.utils.logger import logger

STRATEGY = "SPECIALIST"


def execute_signal(
    signal: Signal,
    run_id: str,
    total_capital: float,
) -> Optional[dict]:
    """
    Execute a Signal as a paper trade. Returns the clob_exec result dict
    or None if execution failed.
    """
    # Determine outcome_token_id from the market.
    # Try tokens list first; fall back to clobTokenIds[0=YES, 1=NO].
    market = signal.market
    tokens = market.get("tokens") or []
    outcome_token_id = None
    for tok in tokens:
        outcome = (tok.get("outcome") or "").upper()
        if outcome == signal.direction:
            outcome_token_id = tok.get("token_id") or tok.get("tokenId")
            break

    if not outcome_token_id:
        # Gamma API: clobTokenIds may be a JSON-encoded string [yes_id, no_id]
        raw_ids = market.get("clobTokenIds") or []
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except (json.JSONDecodeError, ValueError):
                raw_ids = []
        if len(raw_ids) >= 2:
            outcome_token_id = str(raw_ids[0] if signal.direction == "YES" else raw_ids[1])

    if not outcome_token_id:
        logger.warning(
            f"  executor: no token_id for {signal.direction} in {signal.condition_id[:12]}…"
        )
        return None

    # Size calculation
    uni_cap = universe_capital(signal.universe, total_capital)
    size_usd = uni_cap * C.SPECIALIST_TRADE_PCT
    size_usd = min(size_usd, C.SPECIALIST_MAX_TRADE_USD)
    size_usd = max(size_usd, C.SPECIALIST_MIN_TRADE_USD)

    # Spread check — reject if bid-ask spread exceeds the configured threshold.
    # Two sequential CLOB calls (ask + bid); only blocks if both prices are
    # available and spread is confirmed wide. If the CLOB is unreachable,
    # open_paper_trade() will fail on its own price fetch.
    ask, bid = clob_exec.get_spread(outcome_token_id)
    if ask is not None and bid is not None:
        spread = round(ask - bid, 4)
        if spread > C.SPECIALIST_MARKET_MAX_SPREAD:
            logger.info(
                f"  executor: skip {signal.condition_id[:12]}… "
                f"spread={spread:.4f} (ask={ask:.4f} bid={bid:.4f}) "
                f"> max={C.SPECIALIST_MARKET_MAX_SPREAD} — will retry next tick"
            )
            return None

    logger.info(
        f"  executor: opening {signal.direction} ${size_usd:.2f} "
        f"in {signal.condition_id[:12]}… [{signal.quality.value}] "
        f"specialists={signal.specialists_for}/{signal.specialists_against} "
        f"eROI={signal.expected_roi:.1%}"
    )

    metadata = {
        "universe": signal.universe,
        "market_type": signal.market_type,
        "signal_quality": signal.quality.value,
        "expected_roi": signal.expected_roi,
        "specialists_count": signal.specialists_for,
        "specialists_against": signal.specialists_against,
        "ratio": signal.ratio,
        "avg_hit_rate": signal.avg_hit_rate,
        "trailing_active": False,
        "high_water_mark": None,
    }

    result = clob_exec.open_paper_trade(
        strategy=STRATEGY,
        market_polymarket_id=signal.condition_id,
        outcome_token_id=outcome_token_id,
        direction=signal.direction,
        size_usd=size_usd,
        run_id=run_id,
        market_question=market.get("question"),
        market_category=signal.universe,
        metadata=metadata,
    )

    if result.get("real"):
        logger.info(
            f"  executor: trade opened real={result['real'][:8]}… "
            f"shadow={str(result.get('shadow') or '')[:8]}…"
        )
    else:
        logger.warning(f"  executor: real trade not opened (risk blocked or price failed)")

    return result
