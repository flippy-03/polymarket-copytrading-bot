"""
Paper / live execution abstraction + shadow trade bookkeeping.

In PAPER_MODE (default, used for the backtest) all trades are synthetic: we
record an OPEN row in copy_trades using the current CLOB midpoint as entry
price, and close it later when a close signal arrives (the exit price comes
from a fresh CLOB query at close time).

Every real trade is mirrored with a shadow trade at fixed size ($100) with
is_shadow=True. Shadow trades bypass risk checks and track two closes:
  - "stops" side: STOP_LOSS_PCT / TAKE_PROFIT_PCT evaluated on each tick.
  - "pure" side: held until the real exit signal (or timeout / resolution).

Shadow trades are also generated when the real trade is rejected by risk,
so we can evaluate pure signal quality independent of execution constraints.

Live mode is not implemented yet — keep PAPER_MODE=true.
"""
import httpx

from src.strategies.common import config as C
from src.strategies.common import db, risk_manager_ct as risk
from src.utils.logger import logger


_clob = httpx.Client(base_url=C.CLOB_API, timeout=15.0)

SHADOW_FIXED_SIZE_USD = 100.0
SHADOW_STOP_LOSS_PCT = -0.15
SHADOW_TAKE_PROFIT_PCT = 0.20


def get_token_price(token_id: str) -> float | None:
    try:
        r = _clob.get("/price", params={"token_id": token_id, "side": "BUY"})
        r.raise_for_status()
        return float(r.json().get("price") or 0)
    except Exception as e:
        logger.debug(f"CLOB /price failed for {token_id[:8]}…: {e}")
        return None


def _record_price(token_id: str, price: float, market_id: str | None) -> None:
    db.record_price_snapshot(token_id, price, market_polymarket_id=market_id)


def _open_row(
    *,
    run_id: str,
    strategy: str,
    market_polymarket_id: str,
    outcome_token_id: str,
    direction: str,
    size_usd: float,
    price: float,
    signal_id: str | None,
    source_wallet: str | None,
    market_question: str | None,
    market_category: str | None,
    metadata: dict | None,
    is_shadow: bool,
) -> str:
    shares = round(size_usd / price, 4)
    md = dict(metadata or {})
    if is_shadow:
        md.setdefault("shadow_stop_price", round(price * (1 + SHADOW_STOP_LOSS_PCT), 4))
        md.setdefault("shadow_take_price", round(price * (1 + SHADOW_TAKE_PROFIT_PCT), 4))
    return db.open_copy_trade({
        "run_id": run_id,
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
        "is_shadow": is_shadow,
        "metadata": md,
    })


def _increment_open_positions(strategy: str, run_id: str, is_shadow: bool) -> None:
    p = db.get_portfolio(strategy, run_id=run_id, is_shadow=is_shadow)
    if p:
        db.update_portfolio(
            strategy,
            {"open_positions": int(p.get("open_positions") or 0) + 1},
            run_id=run_id,
            is_shadow=is_shadow,
        )


def _decrement_open_positions(strategy: str, run_id: str, is_shadow: bool) -> None:
    p = db.get_portfolio(strategy, run_id=run_id, is_shadow=is_shadow)
    if p:
        db.update_portfolio(
            strategy,
            {"open_positions": max(int(p.get("open_positions") or 0) - 1, 0)},
            run_id=run_id,
            is_shadow=is_shadow,
        )


def open_paper_trade(
    strategy: str,
    market_polymarket_id: str,
    outcome_token_id: str,
    direction: str,                 # "YES" | "NO"
    size_usd: float,
    *,
    run_id: str,
    signal_id: str | None = None,
    source_wallet: str | None = None,
    market_question: str | None = None,
    market_category: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Try to open a real trade (subject to risk gating) and ALWAYS open a shadow
    trade in parallel (fixed $100, no risk gating). Returns:
        {"real": trade_id | None, "shadow": trade_id | None, "price": float | None}
    """
    price = get_token_price(outcome_token_id)
    if not price or price <= 0:
        logger.warning(f"[{strategy}] no CLOB price for {outcome_token_id[:8]}…")
        return {"real": None, "shadow": None, "price": None}
    _record_price(outcome_token_id, price, market_polymarket_id)

    out: dict = {"real": None, "shadow": None, "price": price}

    ok, reason = risk.can_open_position(strategy, run_id=run_id)
    if not ok:
        logger.info(f"[{strategy}] risk blocked real: {reason}")
    else:
        real_id = _open_row(
            run_id=run_id, strategy=strategy,
            market_polymarket_id=market_polymarket_id,
            outcome_token_id=outcome_token_id,
            direction=direction, size_usd=size_usd, price=price,
            signal_id=signal_id, source_wallet=source_wallet,
            market_question=market_question, market_category=market_category,
            metadata=metadata, is_shadow=False,
        )
        _increment_open_positions(strategy, run_id, False)
        logger.info(f"[{strategy}] OPEN {direction} ${size_usd:.2f} @ {price:.3f} → real {real_id[:8]}")
        out["real"] = real_id

    # Shadow: always open (fixed size, no gating).
    shadow_id = _open_row(
        run_id=run_id, strategy=strategy,
        market_polymarket_id=market_polymarket_id,
        outcome_token_id=outcome_token_id,
        direction=direction, size_usd=SHADOW_FIXED_SIZE_USD, price=price,
        signal_id=signal_id, source_wallet=source_wallet,
        market_question=market_question, market_category=market_category,
        metadata={**(metadata or {}), "real_trade_id": out["real"]},
        is_shadow=True,
    )
    _increment_open_positions(strategy, run_id, True)
    logger.info(f"[{strategy}] OPEN shadow ${SHADOW_FIXED_SIZE_USD:.0f} @ {price:.3f} → {shadow_id[:8]}")
    out["shadow"] = shadow_id
    return out


def _pnl(shares: float, entry_price: float, exit_price: float, position_usd: float) -> tuple[float, float]:
    pnl_usd = shares * (exit_price - entry_price)
    pnl_pct = pnl_usd / position_usd if position_usd else 0.0
    return pnl_usd, pnl_pct


def close_paper_trade(trade_id: str, reason: str) -> None:
    """Close a real (is_shadow=false) trade using the current CLOB price."""
    from src.db import supabase_client as _db
    client = _db.get_client()
    result = client.table("copy_trades").select("*").eq("id", trade_id).limit(1).execute()
    if not result.data:
        logger.warning(f"close_paper_trade: trade {trade_id} not found")
        return
    t = result.data[0]
    if t["status"] != "OPEN":
        return
    if t.get("is_shadow"):
        logger.warning(f"close_paper_trade called on shadow {trade_id[:8]} — use close_shadow_trade")
        return

    exit_price = get_token_price(t["outcome_token_id"]) or float(t["entry_price"])
    _record_price(t["outcome_token_id"], exit_price, t.get("market_polymarket_id"))
    pnl_usd, pnl_pct = _pnl(float(t["shares"]), float(t["entry_price"]), exit_price, float(t["position_usd"]))

    db.close_copy_trade(trade_id, round(exit_price, 4), pnl_usd, pnl_pct, reason)
    db.apply_trade_to_portfolio(
        t["strategy"], pnl_usd, is_win=pnl_usd > 0, run_id=t["run_id"], is_shadow=False,
    )
    _decrement_open_positions(t["strategy"], t["run_id"], False)
    risk.register_loss_and_maybe_break(t["strategy"], pnl_pct, run_id=t["run_id"])
    logger.info(f"[{t['strategy']}] CLOSE {trade_id[:8]} @ {exit_price:.3f} PnL=${pnl_usd:.2f} ({pnl_pct:+.1%}) — {reason}")


def close_shadow_trade(trade_id: str, reason: str) -> None:
    """
    Close the 'pure' side of a shadow trade with the current CLOB price.
    If the stops side was never triggered, mirror pure → stops.
    """
    from src.db import supabase_client as _db
    client = _db.get_client()
    result = client.table("copy_trades").select("*").eq("id", trade_id).limit(1).execute()
    if not result.data:
        return
    t = result.data[0]
    if t["status"] != "OPEN" or not t.get("is_shadow"):
        return

    exit_price = get_token_price(t["outcome_token_id"]) or float(t["entry_price"])
    _record_price(t["outcome_token_id"], exit_price, t.get("market_polymarket_id"))
    pnl_usd, pnl_pct = _pnl(float(t["shares"]), float(t["entry_price"]), exit_price, float(t["position_usd"]))

    db.close_shadow_pure(trade_id, round(exit_price, 4), pnl_usd, pnl_pct, reason)
    # Shadow portfolio accounting: use the stops-side numbers if they were
    # frozen earlier (= what actually happened for the shadow), otherwise pure.
    freshened = client.table("copy_trades").select("pnl_usd,pnl_pct").eq("id", trade_id).limit(1).execute().data
    realized_pnl_usd = float((freshened[0].get("pnl_usd") if freshened else None) or pnl_usd)
    db.apply_trade_to_portfolio(
        t["strategy"], realized_pnl_usd, is_win=realized_pnl_usd > 0,
        run_id=t["run_id"], is_shadow=True,
    )
    _decrement_open_positions(t["strategy"], t["run_id"], True)
    logger.info(
        f"[{t['strategy']}] CLOSE shadow {trade_id[:8]} @ {exit_price:.3f} "
        f"pure=${pnl_usd:.2f} stops=${realized_pnl_usd:.2f} — {reason}"
    )


def evaluate_shadow_stops(strategy: str, *, run_id: str) -> int:
    """
    For every OPEN shadow trade whose 'stops' side is still unset, fetch the
    current CLOB price and check STOP_LOSS_PCT / TAKE_PROFIT_PCT. Freezes
    the stops side in place without closing the trade (pure keeps running).
    Returns the number of trades whose stops side got frozen this tick.
    """
    shadows = db.list_open_shadow_trades_needing_stops(strategy, run_id=run_id)
    frozen = 0
    for t in shadows:
        token_id = t.get("outcome_token_id")
        if not token_id:
            continue
        price = get_token_price(token_id)
        if price is None:
            continue
        _record_price(token_id, price, t.get("market_polymarket_id"))
        pnl_usd, pnl_pct = _pnl(
            float(t["shares"]), float(t["entry_price"]), price, float(t["position_usd"])
        )
        reason = None
        if pnl_pct <= SHADOW_STOP_LOSS_PCT:
            reason = "STOP_LOSS"
        elif pnl_pct >= SHADOW_TAKE_PROFIT_PCT:
            reason = "TAKE_PROFIT"
        if reason:
            db.close_shadow_stops(t["id"], round(price, 4), pnl_usd, pnl_pct, reason)
            frozen += 1
    return frozen
