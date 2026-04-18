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
from src.strategies.common import clob_exec, db
from src.strategies.specialist.signal_generator import Signal, SignalQuality
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
    if signal.quality == SignalQuality.CONTESTED:
        size_usd *= C.SPECIALIST_CONTESTED_SIZE_MULT
    size_usd = min(size_usd, C.SPECIALIST_MAX_TRADE_USD)
    size_usd = max(size_usd, C.SPECIALIST_MIN_TRADE_USD)

    # Dynamic exposure cap: total open positions ≤ 50% of portfolio
    max_exposure = total_capital * C.SPECIALIST_MAX_EXPOSURE_PCT
    current_exposure = db.get_current_specialist_exposure(run_id)
    available = max_exposure - current_exposure
    if available < C.SPECIALIST_MIN_TRADE_USD:
        logger.info(
            f"  executor: exposure cap reached "
            f"(open=${current_exposure:.0f} / max=${max_exposure:.0f}) — skipping"
        )
        return None
    if size_usd > available:
        size_usd = round(available, 2)
        logger.info(f"  executor: size trimmed to ${size_usd:.2f} (exposure headroom)")

    # Spread + CLOB price range check.
    # get_spread() gives us both ask and bid with two CLOB calls.  We reuse
    # those values to (a) block wide spreads and (b) guard against stale Gamma
    # prices — the signal_generator checks price using Gamma market data which
    # can lag the CLOB by several seconds, causing entries at near-certain
    # prices (e.g. $0.999) that offer essentially zero edge.
    ask, bid = clob_exec.get_spread(outcome_token_id)
    clob_ask = ask  # may be None if CLOB unreachable — checked below
    if ask is not None and bid is not None:
        spread = round(ask - bid, 4)
        if spread > C.SPECIALIST_MARKET_MAX_SPREAD:
            logger.info(
                f"  executor: skip {signal.condition_id[:12]}… "
                f"spread={spread:.4f} (ask={ask:.4f} bid={bid:.4f}) "
                f"> max={C.SPECIALIST_MARKET_MAX_SPREAD} — will retry next tick"
            )
            return None

    # CLOB price range guard — mirrors SPECIALIST_MARKET_MIN/MAX_PRICE but
    # uses the live CLOB ask rather than the Gamma-sourced price in the signal.
    # Rejects if the token is now trading outside the allowed range.
    if clob_ask is not None:
        if clob_ask < C.SPECIALIST_MARKET_MIN_PRICE or clob_ask > C.SPECIALIST_MARKET_MAX_PRICE:
            logger.info(
                f"  executor: skip {signal.condition_id[:12]}… "
                f"CLOB ask={clob_ask:.4f} out of range "
                f"[{C.SPECIALIST_MARKET_MIN_PRICE}, {C.SPECIALIST_MARKET_MAX_PRICE}] "
                f"— Gamma price was stale, will retry next tick"
            )
            return None

    logger.info(
        f"  executor: opening {signal.direction} ${size_usd:.2f} "
        f"in {signal.condition_id[:12]}… [{signal.quality.value}] "
        f"specialists={signal.specialists_for}/{signal.specialists_against} "
        f"eROI={signal.expected_roi:.1%}"
    )

    # Market close time — prefer sport gameStartTime (when trading stops),
    # fall back to endDate for crypto/financial (daily resolution).
    closes_at = (
        market.get("gameStartTime")
        or market.get("endDate")
        or market.get("endDateIso")
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
        "confidence": signal.confidence,
        "event_slug": signal.event_slug,
        "closes_at": closes_at,
        "trailing_active": False,
        "high_water_mark": None,
        "low_water_mark": None,
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
