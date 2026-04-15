"""
Persistence helpers for the copytrading stack.

All new tables introduced by 002_copytrading.sql are accessed through this
module. Under the hood we reuse src.db.supabase_client for CRUD.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from src.db import supabase_client as _db
from src.strategies.common.wallet_analyzer import WalletMetrics
from src.utils.logger import logger


def _iso(ts: int | float | None) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── runs ─────────────────────────────────────────────────
# Each strategy has exactly one ACTIVE run at a time (enforced by a partial
# unique index). All strategy-derived writes carry a run_id; callers resolve
# the active run once per loop via get_active_run(strategy).

_active_run_cache: dict[str, str] = {}


def get_active_run(strategy: str, *, use_cache: bool = True) -> str:
    """Return the id of the ACTIVE run for `strategy`. Raises if none exists."""
    if use_cache and strategy in _active_run_cache:
        return _active_run_cache[strategy]
    client = _db.get_client()
    result = (
        client.table("runs")
        .select("id")
        .eq("strategy", strategy)
        .eq("status", "ACTIVE")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise RuntimeError(
            f"No ACTIVE run for strategy={strategy}. Seed one via 003 migration "
            f"or scripts/close_run.py."
        )
    run_id = result.data[0]["id"]
    _active_run_cache[strategy] = run_id
    return run_id


def get_run(run_id: str) -> dict | None:
    rows = _db.select("runs", {"id": run_id})
    return rows[0] if rows else None


def list_runs(strategy: Optional[str] = None) -> list[dict]:
    client = _db.get_client()
    q = client.table("runs").select("*").order("started_at", desc=True)
    if strategy:
        q = q.eq("strategy", strategy)
    return q.execute().data


def create_run(
    strategy: str,
    version: str,
    *,
    notes: str | None = None,
    parent_run_id: str | None = None,
    config_snapshot: dict | None = None,
) -> str:
    """Insert a new ACTIVE run. Caller must have closed the previous one first."""
    row = _db.insert(
        "runs",
        {
            "strategy": strategy,
            "version": version,
            "status": "ACTIVE",
            "notes": notes,
            "parent_run_id": parent_run_id,
            "config_snapshot": config_snapshot or {},
        },
    )[0]
    _active_run_cache[strategy] = row["id"]
    return row["id"]


def close_run(run_id: str, *, end_notes: str | None = None) -> None:
    """Mark a run as CLOSED. Does not touch its trades."""
    patch: dict[str, Any] = {"status": "CLOSED", "ended_at": _now_iso()}
    if end_notes is not None:
        patch["notes"] = end_notes
    _db.update("runs", match={"id": run_id}, data=patch)
    # Invalidate any cached active-run pointer that may have matched this id.
    for k, v in list(_active_run_cache.items()):
        if v == run_id:
            _active_run_cache.pop(k, None)


def clear_active_run_cache(strategy: str | None = None) -> None:
    if strategy is None:
        _active_run_cache.clear()
    else:
        _active_run_cache.pop(strategy, None)


# ── wallets ──────────────────────────────────────────────

def upsert_wallet(address: str) -> None:
    _db.upsert("wallets", {"address": address, "last_analyzed": _now_iso()}, on_conflict="address")


def set_quarantine(address: str, until_ts: int, reason: str) -> None:
    _db.update(
        "wallets",
        match={"address": address},
        data={
            "is_quarantined": True,
            "quarantine_until": _iso(until_ts),
            "quarantine_reason": reason,
        },
    )


def clear_quarantine(address: str) -> None:
    _db.update(
        "wallets",
        match={"address": address},
        data={"is_quarantined": False, "quarantine_until": None, "quarantine_reason": None},
    )


# ── wallet_metrics ───────────────────────────────────────

def save_wallet_metrics(
    m: WalletMetrics,
    tier1_pass: bool,
    tier2_score: int,
    tier3_alerts: list[str],
    is_bot: bool,
    bot_score: int,
    sharpe_14d: float | None = None,
    composite_score: float | None = None,
    *,
    run_id: str,
) -> None:
    upsert_wallet(m.address)
    row = {
        "run_id": run_id,
        "wallet_address": m.address,
        "win_rate": round(m.win_rate, 4),
        "total_trades": m.total_trades,
        "track_record_days": m.track_record_days,
        "avg_holding_days": round(m.avg_holding_period_hours / 24, 2),
        "trades_per_month": round(m.trades_per_month, 2),
        "pnl_30d": round(m.pnl_30d, 2),
        "pnl_7d": round(m.pnl_7d, 2),
        "tier1_pass": tier1_pass,
        "profit_factor": None if m.profit_factor == float("inf") else round(m.profit_factor, 2),
        "edge_vs_odds": round(m.edge_vs_odds, 4),
        "market_categories": m.unique_categories,
        "positive_weeks_pct": round(m.positive_weeks_pct, 4),
        "avg_position_size": round(m.avg_position_size, 2),
        "tier2_score": tier2_score,
        "tier3_alerts": tier3_alerts,
        "bot_interval_cv": round(m.interval_cv, 4),
        "bot_size_cv": round(m.size_cv, 4),
        "bot_delay_correlation": round(m.max_corr_delay, 4),
        "bot_unique_market_pct": round(m.unique_markets_pct, 4),
        "bot_score": bot_score,
        "is_bot": is_bot,
        "sharpe_14d": round(sharpe_14d, 4) if sharpe_14d is not None else None,
        "composite_score": round(composite_score, 4) if composite_score is not None else None,
    }
    _db.insert("wallet_metrics", row)


# ── baskets ──────────────────────────────────────────────

def get_or_create_basket(category: str) -> str:
    client = _db.get_client()
    result = client.table("baskets").select("id").eq("category", category).eq("status", "ACTIVE").limit(1).execute()
    if result.data:
        return result.data[0]["id"]
    row = _db.insert("baskets", {"category": category, "status": "ACTIVE"})[0]
    return row["id"]


def replace_basket_wallets(basket_id: str, wallets: list[dict], *, run_id: str) -> None:
    """
    wallets: list of {"address", "rank_score", "rank_position"}.
    Rebuild membership within the given run: rows from the same (run_id, basket_id)
    not present in the new set are marked exited; new rows are upserted.
    """
    client = _db.get_client()
    existing = (
        client.table("basket_wallets")
        .select("wallet_address")
        .eq("run_id", run_id)
        .eq("basket_id", basket_id)
        .is_("exited_at", "null")
        .execute()
        .data
    )
    new_addrs = {w["address"] for w in wallets}
    for row in existing:
        if row["wallet_address"] not in new_addrs:
            _db.update(
                "basket_wallets",
                match={
                    "run_id": run_id,
                    "basket_id": basket_id,
                    "wallet_address": row["wallet_address"],
                },
                data={"exited_at": _now_iso(), "exit_reason": "REBUILD"},
            )
    for w in wallets:
        upsert_wallet(w["address"])
        _db.upsert(
            "basket_wallets",
            {
                "run_id": run_id,
                "basket_id": basket_id,
                "wallet_address": w["address"],
                "rank_score": w.get("rank_score"),
                "rank_position": w.get("rank_position"),
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="run_id,basket_id,wallet_address",
        )


def carry_over_basket_wallets(source_run_id: str, target_run_id: str) -> int:
    """
    On run open: copy the currently-active basket_wallets rows from source_run_id
    to target_run_id so the new run starts with the same members. Returns the
    number of rows re-stamped.
    """
    client = _db.get_client()
    existing = (
        client.table("basket_wallets")
        .select("basket_id, wallet_address, rank_score, rank_position")
        .eq("run_id", source_run_id)
        .is_("exited_at", "null")
        .execute()
        .data
    )
    for row in existing:
        _db.upsert(
            "basket_wallets",
            {
                "run_id": target_run_id,
                "basket_id": row["basket_id"],
                "wallet_address": row["wallet_address"],
                "rank_score": row.get("rank_score"),
                "rank_position": row.get("rank_position"),
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="run_id,basket_id,wallet_address",
        )
    return len(existing)


def get_active_basket_wallets(basket_id: str, *, run_id: str) -> list[str]:
    client = _db.get_client()
    result = (
        client.table("basket_wallets")
        .select("wallet_address")
        .eq("run_id", run_id)
        .eq("basket_id", basket_id)
        .is_("exited_at", "null")
        .execute()
    )
    return [r["wallet_address"] for r in result.data]


def list_active_baskets() -> list[dict]:
    return _db.select("baskets", {"status": "ACTIVE"})


# ── scalper_pool ─────────────────────────────────────────

def set_scalper_pool(entries: list[dict], *, run_id: str) -> None:
    """
    entries: list of {"address", "sharpe_14d", "rank_position", "status"}.
    Replaces the pool for this run atomically (upsert each + mark old ones removed).
    """
    client = _db.get_client()
    existing = (
        client.table("scalper_pool")
        .select("wallet_address")
        .eq("run_id", run_id)
        .execute()
        .data
    )
    new_addrs = {e["address"] for e in entries}
    for row in existing:
        if row["wallet_address"] not in new_addrs:
            _db.update(
                "scalper_pool",
                match={"run_id": run_id, "wallet_address": row["wallet_address"]},
                data={"status": "POOL", "exited_at": _now_iso(), "exit_reason": "REBUILD"},
            )
    for e in entries:
        upsert_wallet(e["address"])
        _db.upsert(
            "scalper_pool",
            {
                "run_id": run_id,
                "wallet_address": e["address"],
                "status": e.get("status", "POOL"),
                "sharpe_14d": e.get("sharpe_14d"),
                "rank_position": e.get("rank_position"),
                "capital_allocated_usd": e.get("capital_allocated_usd", 0),
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="run_id,wallet_address",
        )


def carry_over_scalper_pool(source_run_id: str, target_run_id: str) -> int:
    """Copy active scalper_pool rows from source_run_id to target_run_id."""
    client = _db.get_client()
    existing = (
        client.table("scalper_pool")
        .select("wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd")
        .eq("run_id", source_run_id)
        .is_("exited_at", "null")
        .execute()
        .data
    )
    for row in existing:
        _db.upsert(
            "scalper_pool",
            {
                "run_id": target_run_id,
                "wallet_address": row["wallet_address"],
                "status": row.get("status") or "POOL",
                "sharpe_14d": row.get("sharpe_14d"),
                "rank_position": row.get("rank_position"),
                "capital_allocated_usd": row.get("capital_allocated_usd") or 0,
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="run_id,wallet_address",
        )
    return len(existing)


def list_scalper_pool(status: Optional[str] = None, *, run_id: str) -> list[dict]:
    client = _db.get_client()
    q = client.table("scalper_pool").select("*").eq("run_id", run_id)
    if status:
        q = q.eq("status", status)
    return q.execute().data


def update_scalper_status(address: str, status: str, capital_usd: float = 0, *, run_id: str) -> None:
    _db.update(
        "scalper_pool",
        match={"run_id": run_id, "wallet_address": address},
        data={"status": status, "capital_allocated_usd": capital_usd},
    )


# ── consensus_signals ────────────────────────────────────

def insert_consensus_signal(row: dict, *, run_id: str) -> str:
    row = {"created_at": _now_iso(), "run_id": run_id, **row}
    result = _db.insert("consensus_signals", row)
    return result[0]["id"]


def mark_signal_executed(signal_id: str) -> None:
    _db.update(
        "consensus_signals",
        match={"id": signal_id},
        data={"status": "EXECUTED", "executed_at": _now_iso()},
    )


def list_pending_signals(*, run_id: str) -> list[dict]:
    client = _db.get_client()
    return (
        client.table("consensus_signals")
        .select("*")
        .eq("run_id", run_id)
        .eq("status", "PENDING")
        .execute()
        .data
    )


# ── copy_trades ──────────────────────────────────────────

def open_copy_trade(row: dict) -> str:
    """
    row must include run_id, strategy, and is_shadow (default false).
    Shadow trades share the same table — queries filter with is_shadow.
    """
    if "run_id" not in row:
        raise ValueError("open_copy_trade: row missing run_id")
    row = {
        "status": "OPEN",
        "opened_at": _now_iso(),
        "is_paper": True,
        "is_shadow": False,
        **row,
    }
    result = _db.insert("copy_trades", row)
    return result[0]["id"]


def close_copy_trade(trade_id: str, exit_price: float, pnl_usd: float, pnl_pct: float, reason: str) -> None:
    """
    Closes the 'stops' side of a trade (= the real trade for non-shadow rows, or
    the stops-applied evaluation for shadow rows). For shadow rows, the 'pure'
    side is closed separately via close_shadow_pure().
    """
    _db.update(
        "copy_trades",
        match={"id": trade_id},
        data={
            "status": "CLOSED",
            "exit_price": exit_price,
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 4),
            "close_reason": reason,
            "closed_at": _now_iso(),
        },
    )


def close_shadow_stops(trade_id: str, exit_price: float, pnl_usd: float, pnl_pct: float, reason: str) -> None:
    """
    Freeze the 'stops' side of a shadow trade without closing it. The trade
    stays OPEN so the 'pure' side can keep running until resolution.
    """
    _db.update(
        "copy_trades",
        match={"id": trade_id},
        data={
            "exit_price": round(exit_price, 4),
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 4),
            "close_reason": reason,
        },
    )


def close_shadow_pure(
    trade_id: str,
    exit_price: float,
    pnl_usd: float,
    pnl_pct: float,
    reason: str,
    *,
    also_mirror_stops_if_unset: bool = True,
) -> None:
    """
    Close the 'pure' side of a shadow trade (held to resolution/timeout) and
    mark the trade as CLOSED. If the stops side was never triggered, its
    columns get mirrored from pure to keep aggregates consistent.
    """
    client = _db.get_client()
    current = (
        client.table("copy_trades")
        .select("exit_price,pnl_usd,pnl_pct,close_reason,status")
        .eq("id", trade_id)
        .limit(1)
        .execute()
        .data
    )
    patch: dict[str, Any] = {
        "status": "CLOSED",
        "exit_price_pure": round(exit_price, 4),
        "pnl_pure_usd": round(pnl_usd, 4),
        "pnl_pure_pct": round(pnl_pct, 4),
        "close_reason_pure": reason,
        "closed_at_pure": _now_iso(),
    }
    if current and also_mirror_stops_if_unset and current[0].get("exit_price") is None:
        patch.update({
            "exit_price": round(exit_price, 4),
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 4),
            "close_reason": reason,
            "closed_at": _now_iso(),
        })
    _db.update("copy_trades", match={"id": trade_id}, data=patch)


def list_open_trades(
    strategy: Optional[str] = None,
    *,
    run_id: str,
    is_shadow: bool = False,
) -> list[dict]:
    client = _db.get_client()
    q = (
        client.table("copy_trades")
        .select("*")
        .eq("status", "OPEN")
        .eq("run_id", run_id)
        .eq("is_shadow", is_shadow)
    )
    if strategy:
        q = q.eq("strategy", strategy)
    return q.execute().data


def list_open_shadow_trades_needing_stops(strategy: Optional[str] = None, *, run_id: str) -> list[dict]:
    """Shadow trades whose 'stops' side has not been triggered yet."""
    client = _db.get_client()
    q = (
        client.table("copy_trades")
        .select("*")
        .eq("status", "OPEN")
        .eq("run_id", run_id)
        .eq("is_shadow", True)
        .is_("exit_price", "null")
    )
    if strategy:
        q = q.eq("strategy", strategy)
    return q.execute().data


# ── portfolio_state_ct ───────────────────────────────────
# Keyed by (strategy, run_id, is_shadow). Every strategy has two rows per run:
# the real portfolio and the shadow portfolio tracking signal-pure outcomes.

def get_portfolio(strategy: str, *, run_id: str, is_shadow: bool = False) -> dict | None:
    rows = _db.select(
        "portfolio_state_ct",
        {"strategy": strategy, "run_id": run_id, "is_shadow": is_shadow},
    )
    return rows[0] if rows else None


def ensure_portfolio_row(
    strategy: str,
    *,
    run_id: str,
    is_shadow: bool,
    initial_capital: float,
    max_open_positions: int,
) -> None:
    """Create the portfolio row for (strategy, run_id, is_shadow) if missing."""
    if get_portfolio(strategy, run_id=run_id, is_shadow=is_shadow) is not None:
        return
    _db.insert(
        "portfolio_state_ct",
        {
            "strategy": strategy,
            "run_id": run_id,
            "is_shadow": is_shadow,
            "initial_capital": initial_capital,
            "current_capital": initial_capital,
            "max_open_positions": max_open_positions,
        },
    )


def update_portfolio(strategy: str, data: dict, *, run_id: str, is_shadow: bool = False) -> None:
    data = {"updated_at": _now_iso(), **data}
    _db.update(
        "portfolio_state_ct",
        match={"strategy": strategy, "run_id": run_id, "is_shadow": is_shadow},
        data=data,
    )


def apply_trade_to_portfolio(
    strategy: str,
    pnl_usd: float,
    is_win: bool,
    *,
    run_id: str,
    is_shadow: bool = False,
) -> None:
    p = get_portfolio(strategy, run_id=run_id, is_shadow=is_shadow)
    if not p:
        logger.warning(
            f"No portfolio row for strategy={strategy} run={run_id[:8]} shadow={is_shadow}"
        )
        return
    new_capital = float(p["current_capital"]) + pnl_usd
    total_trades = int(p.get("total_trades") or 0) + 1
    wins = int(p.get("winning_trades") or 0) + (1 if is_win else 0)
    losses = int(p.get("losing_trades") or 0) + (0 if is_win else 1)
    initial = float(p["initial_capital"])
    total_pnl = new_capital - initial
    update_portfolio(
        strategy,
        {
            "current_capital": round(new_capital, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / initial) if initial > 0 else 0, 6),
            "total_trades": total_trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(wins / total_trades, 4) if total_trades else 0,
        },
        run_id=run_id,
        is_shadow=is_shadow,
    )


# ── rotation_history ─────────────────────────────────────

def insert_rotation(
    reason: str,
    removed_titulars: list[dict],
    new_titulars: list[dict],
    pool_snapshot: list[dict],
    *,
    run_id: str,
) -> None:
    _db.insert(
        "rotation_history",
        {
            "run_id": run_id,
            "reason": reason,
            "removed_titulars": removed_titulars,
            "new_titulars": new_titulars,
            "pool_snapshot": pool_snapshot,
        },
    )


# ── raw data recorders (no run_id — immutable, replayable across runs) ──

def record_observed_trade(
    wallet_address: str,
    *,
    tx_hash: str | None,
    traded_at: str | None,
    market_polymarket_id: str,
    market_question: str | None = None,
    outcome_token_id: str | None = None,
    outcome_label: str | None = None,
    direction: str | None = None,
    side: str | None = None,
    price: float | None = None,
    size: float | None = None,
    usdc_size: float | None = None,
    raw: dict | None = None,
) -> None:
    """Fire-and-forget: dedupe on (wallet_address, tx_hash, outcome_token_id)."""
    row = {
        "wallet_address": wallet_address,
        "tx_hash": tx_hash,
        "traded_at": traded_at,
        "market_polymarket_id": market_polymarket_id,
        "market_question": market_question,
        "outcome_token_id": outcome_token_id,
        "outcome_label": outcome_label,
        "direction": direction,
        "side": side,
        "price": price,
        "size": size,
        "usdc_size": usdc_size,
        "raw": raw,
    }
    try:
        _db.insert("observed_trades", row)
    except Exception as e:
        # dedupe collision is fine, anything else we log softly
        if "duplicate" not in str(e).lower():
            logger.debug(f"record_observed_trade: {e}")


def record_price_snapshot(
    outcome_token_id: str,
    price: float,
    *,
    market_polymarket_id: str | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    liquidity_usd: float | None = None,
    source: str = "CLOB",
) -> None:
    try:
        _db.insert(
            "market_price_snapshots",
            {
                "outcome_token_id": outcome_token_id,
                "market_polymarket_id": market_polymarket_id,
                "price": price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "liquidity_usd": liquidity_usd,
                "source": source,
            },
        )
    except Exception as e:
        logger.debug(f"record_price_snapshot: {e}")


def record_position_snapshot(
    wallet_address: str,
    positions: list[dict],
    *,
    total_value_usd: float | None = None,
) -> None:
    try:
        _db.insert(
            "wallet_position_snapshots",
            {
                "wallet_address": wallet_address,
                "total_value_usd": total_value_usd,
                "position_count": len(positions),
                "positions": positions,
            },
        )
    except Exception as e:
        logger.debug(f"record_position_snapshot: {e}")
