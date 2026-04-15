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
) -> None:
    upsert_wallet(m.address)
    row = {
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


def replace_basket_wallets(basket_id: str, wallets: list[dict]) -> None:
    """
    wallets: list of {"address", "rank_score", "rank_position"}.
    Existing rows for this basket are closed (exited_at set) and new ones inserted.
    """
    client = _db.get_client()
    existing = (
        client.table("basket_wallets")
        .select("wallet_address")
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
                match={"basket_id": basket_id, "wallet_address": row["wallet_address"]},
                data={"exited_at": _now_iso(), "exit_reason": "REBUILD"},
            )
    for w in wallets:
        upsert_wallet(w["address"])
        _db.upsert(
            "basket_wallets",
            {
                "basket_id": basket_id,
                "wallet_address": w["address"],
                "rank_score": w.get("rank_score"),
                "rank_position": w.get("rank_position"),
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="basket_id,wallet_address",
        )


def get_active_basket_wallets(basket_id: str) -> list[str]:
    client = _db.get_client()
    result = (
        client.table("basket_wallets")
        .select("wallet_address")
        .eq("basket_id", basket_id)
        .is_("exited_at", "null")
        .execute()
    )
    return [r["wallet_address"] for r in result.data]


def list_active_baskets() -> list[dict]:
    return _db.select("baskets", {"status": "ACTIVE"})


# ── scalper_pool ─────────────────────────────────────────

def set_scalper_pool(entries: list[dict]) -> None:
    """
    entries: list of {"address", "sharpe_14d", "rank_position", "status"}.
    Replaces the current pool atomically (upsert each + mark old ones removed).
    """
    client = _db.get_client()
    existing = client.table("scalper_pool").select("wallet_address").execute().data
    new_addrs = {e["address"] for e in entries}
    for row in existing:
        if row["wallet_address"] not in new_addrs:
            _db.update(
                "scalper_pool",
                match={"wallet_address": row["wallet_address"]},
                data={"status": "POOL", "exited_at": _now_iso(), "exit_reason": "REBUILD"},
            )
    for e in entries:
        upsert_wallet(e["address"])
        _db.upsert(
            "scalper_pool",
            {
                "wallet_address": e["address"],
                "status": e.get("status", "POOL"),
                "sharpe_14d": e.get("sharpe_14d"),
                "rank_position": e.get("rank_position"),
                "capital_allocated_usd": e.get("capital_allocated_usd", 0),
                "entered_at": _now_iso(),
                "exited_at": None,
                "exit_reason": None,
            },
            on_conflict="wallet_address",
        )


def list_scalper_pool(status: Optional[str] = None) -> list[dict]:
    client = _db.get_client()
    q = client.table("scalper_pool").select("*")
    if status:
        q = q.eq("status", status)
    return q.execute().data


def update_scalper_status(address: str, status: str, capital_usd: float = 0) -> None:
    _db.update(
        "scalper_pool",
        match={"wallet_address": address},
        data={"status": status, "capital_allocated_usd": capital_usd},
    )


# ── consensus_signals ────────────────────────────────────

def insert_consensus_signal(row: dict) -> str:
    row = {"created_at": _now_iso(), **row}
    result = _db.insert("consensus_signals", row)
    return result[0]["id"]


def mark_signal_executed(signal_id: str) -> None:
    _db.update(
        "consensus_signals",
        match={"id": signal_id},
        data={"status": "EXECUTED", "executed_at": _now_iso()},
    )


def list_pending_signals() -> list[dict]:
    return _db.select("consensus_signals", {"status": "PENDING"})


# ── copy_trades ──────────────────────────────────────────

def open_copy_trade(row: dict) -> str:
    row = {
        "status": "OPEN",
        "opened_at": _now_iso(),
        "is_paper": True,
        **row,
    }
    result = _db.insert("copy_trades", row)
    return result[0]["id"]


def close_copy_trade(trade_id: str, exit_price: float, pnl_usd: float, pnl_pct: float, reason: str) -> None:
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


def list_open_trades(strategy: Optional[str] = None) -> list[dict]:
    client = _db.get_client()
    q = client.table("copy_trades").select("*").eq("status", "OPEN")
    if strategy:
        q = q.eq("strategy", strategy)
    return q.execute().data


# ── portfolio_state_ct ───────────────────────────────────

def get_portfolio(strategy: str) -> dict | None:
    rows = _db.select("portfolio_state_ct", {"strategy": strategy})
    return rows[0] if rows else None


def update_portfolio(strategy: str, data: dict) -> None:
    data = {"updated_at": _now_iso(), **data}
    _db.update("portfolio_state_ct", match={"strategy": strategy}, data=data)


def apply_trade_to_portfolio(strategy: str, pnl_usd: float, is_win: bool) -> None:
    p = get_portfolio(strategy)
    if not p:
        logger.warning(f"No portfolio row for strategy={strategy}")
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
    )


# ── rotation_history ─────────────────────────────────────

def insert_rotation(
    reason: str,
    removed_titulars: list[dict],
    new_titulars: list[dict],
    pool_snapshot: list[dict],
) -> None:
    _db.insert(
        "rotation_history",
        {
            "reason": reason,
            "removed_titulars": removed_titulars,
            "new_titulars": new_titulars,
            "pool_snapshot": pool_snapshot,
        },
    )
