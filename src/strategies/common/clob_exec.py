"""
Paper / live execution abstraction.

In PAPER_MODE (default, used for the backtest) all trades are synthetic: we record
an OPEN row in copy_trades using the current CLOB midpoint as entry price, and
close it later when a close signal arrives (the exit price comes from a fresh
CLOB query at close time).

Live mode is not implemented yet — keep PAPER_MODE=true.
"""
import time

import httpx

from src.strategies.common import config as C
from src.strategies.common import db, risk_manager_ct as risk
from src.utils.logger import logger


_clob = httpx.Client(base_url=C.CLOB_API, timeout=15.0)


def get_token_price(token_id: str) -> float | None:
    try:
        r = _clob.get("/price", params={"token_id": token_id, "side": "BUY"})
        r.raise_for_status()
        return float(r.json().get("price") or 0)
    except Exception as e:
        logger.debug(f"CLOB /price failed for {token_id[:8]}…: {e}")
        return None


def open_paper_trade(
    strategy: str,
    market_polymarket_id: str,
    outcome_token_id: str,
    direction: str,                 # "YES" | "NO"
    size_usd: float,
    *,
    signal_id: str | None = None,
    source_wallet: str | None = None,
    market_question: str | None = None,
    market_category: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    ok, reason = risk.can_open_position(strategy)
    if not ok:
        logger.info(f"[{strategy}] risk blocked: {reason}")
        return None

    price = get_token_price(outcome_token_id)
    if not price or price <= 0:
        logger.warning(f"[{strategy}] no CLOB price for {outcome_token_id[:8]}…")
        return None

    shares = round(size_usd / price, 4)
    trade_id = db.open_copy_trade({
        "strategy": strategy,
        "signal_id": signal_id,
        "source_wallet": source_wallet,
        "market_polymarket_id": market_polymarket_id,
        "market_question": market_question,
        "market_category": market_category,
        "direction": direction,
        "outcome_token_id": outcome_token_id,
        "entry_price": round(price, 4),
        "shares": shares,
        "position_usd": round(size_usd, 2),
        "metadata": metadata or {},
    })

    p = db.get_portfolio(strategy)
    if p:
        db.update_portfolio(strategy, {"open_positions": int(p.get("open_positions") or 0) + 1})
    logger.info(f"[{strategy}] OPEN {direction} ${size_usd:.2f} @ {price:.3f} → trade {trade_id[:8]}")
    return trade_id


def close_paper_trade(trade_id: str, reason: str) -> None:
    from src.db import supabase_client as _db
    client = _db.get_client()
    result = client.table("copy_trades").select("*").eq("id", trade_id).limit(1).execute()
    if not result.data:
        logger.warning(f"close_paper_trade: trade {trade_id} not found")
        return
    t = result.data[0]
    if t["status"] != "OPEN":
        return

    exit_price = get_token_price(t["outcome_token_id"]) or float(t["entry_price"])
    pnl_usd = float(t["shares"]) * (exit_price - float(t["entry_price"]))
    pnl_pct = pnl_usd / float(t["position_usd"]) if float(t["position_usd"]) else 0.0

    db.close_copy_trade(trade_id, round(exit_price, 4), pnl_usd, pnl_pct, reason)
    db.apply_trade_to_portfolio(t["strategy"], pnl_usd, is_win=pnl_usd > 0)

    p = db.get_portfolio(t["strategy"])
    if p:
        db.update_portfolio(t["strategy"], {"open_positions": max(int(p.get("open_positions") or 0) - 1, 0)})
    risk.register_loss_and_maybe_break(t["strategy"], pnl_pct)
    logger.info(f"[{t['strategy']}] CLOSE {trade_id[:8]} @ {exit_price:.3f} PnL=${pnl_usd:.2f} ({pnl_pct:+.1%}) — {reason}")
