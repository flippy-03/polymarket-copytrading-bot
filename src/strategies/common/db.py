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


def carry_over_spec_ranking(old_run_id: str, new_run_id: str) -> int:
    """Migrate spec_ranking rows from old run to new run (UPDATE in-place).

    Safe because: spec_ranking has no unique constraint, and the old run is
    being closed so it no longer needs its own ranking rows.
    """
    client = _db.get_client()
    try:
        result = (
            client.table("spec_ranking")
            .update({"run_id": new_run_id})
            .eq("run_id", old_run_id)
            .execute()
        )
        return len(result.data or [])
    except Exception as e:
        logger.warning(f"carry_over_spec_ranking: {e}")
        return 0


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


def ensure_wallet(address: str) -> None:
    """Ensure address exists in wallets table (FK parent for scalper_pool)."""
    client = _db.get_client()
    try:
        client.table("wallets").upsert(
            {"address": address}, on_conflict="address"
        ).execute()
    except Exception as e:
        logger.warning(f"ensure_wallet({address[:10]}): {e}")


def upsert_scalper_pool_entry(wallet: str, data: dict, *, run_id: str) -> None:
    """Insert or update a scalper_pool row (safe for new wallets)."""
    ensure_wallet(wallet)
    client = _db.get_client()
    row = {"run_id": run_id, "wallet_address": wallet, **data}
    try:
        client.table("scalper_pool").upsert(
            row, on_conflict="run_id,wallet_address"
        ).execute()
    except Exception as e:
        logger.warning(f"upsert_scalper_pool_entry({wallet[:10]}): {e}")


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


_OPEN_TRADE_COLS = (
    "id,run_id,strategy,status,is_shadow,"
    "market_polymarket_id,outcome_token_id,"
    "entry_price,position_usd,shares,metadata"
)

def get_current_specialist_exposure(run_id: str) -> float:
    """Sum of position_usd for all open non-shadow SPECIALIST trades."""
    client = _db.get_client()
    try:
        rows = (
            client.table("copy_trades")
            .select("position_usd")
            .eq("strategy", "SPECIALIST")
            .eq("run_id", run_id)
            .eq("status", "OPEN")
            .eq("is_shadow", False)
            .execute()
        ).data or []
        return sum(float(r["position_usd"] or 0) for r in rows)
    except Exception as e:
        logger.warning(f"get_current_specialist_exposure: {e}")
        return 0.0


def get_today_opened_condition_ids(run_id: str, strategy: str) -> set[str]:
    """condition_ids for all real trades opened today — blocks same-market re-entries."""
    client = _db.get_client()
    try:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = (
            client.table("copy_trades")
            .select("market_polymarket_id")
            .eq("strategy", strategy)
            .eq("run_id", run_id)
            .eq("is_shadow", False)
            .gte("opened_at", today_utc)
            .execute()
        ).data or []
        return {r["market_polymarket_id"] for r in rows if r.get("market_polymarket_id")}
    except Exception as e:
        logger.warning(f"get_today_opened_condition_ids: {e}")
        return set()


def list_open_trades(
    strategy: Optional[str] = None,
    *,
    run_id: str,
    is_shadow: bool = False,
) -> list[dict]:
    client = _db.get_client()
    q = (
        client.table("copy_trades")
        .select(_OPEN_TRADE_COLS)
        .eq("status", "OPEN")
        .eq("run_id", run_id)
        .eq("is_shadow", is_shadow)
    )
    if strategy:
        q = q.eq("strategy", strategy)
    return q.execute().data


_SHADOW_STOP_COLS = (
    "id,outcome_token_id,market_polymarket_id,"
    "shares,entry_price,position_usd"
)

def list_open_shadow_trades_needing_stops(strategy: Optional[str] = None, *, run_id: str) -> list[dict]:
    """Shadow trades whose 'stops' side has not been triggered yet."""
    client = _db.get_client()
    q = (
        client.table("copy_trades")
        .select(_SHADOW_STOP_COLS)
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


# ── Specialist Edge helpers ──────────────────────────────

def update_copy_trade_metadata(trade_id: str, metadata: dict) -> None:
    """
    Merge new keys into copy_trades.metadata JSON column.
    Used by position_manager to persist trailing stop state.
    """
    client = _db.get_client()
    try:
        existing = (
            client.table("copy_trades")
            .select("metadata")
            .eq("id", trade_id)
            .limit(1)
            .execute()
            .data
        )
        current = (existing[0].get("metadata") or {}) if existing else {}
        merged = {**current, **metadata}
        client.table("copy_trades").update({"metadata": merged}).eq("id", trade_id).execute()
    except Exception as e:
        logger.warning(f"update_copy_trade_metadata {trade_id[:8]}: {e}")


def get_copy_trade(trade_id: str) -> dict | None:
    client = _db.get_client()
    try:
        result = (
            client.table("copy_trades")
            .select("*")
            .eq("id", trade_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"get_copy_trade {trade_id[:8]}: {e}")
        return None


# ── wallet_profiles (enriched dual-strategy wallet fichas) ────────────────────
# Written by the profile_enricher daemon (src/strategies/common/profile_enricher).
# Read by the dashboard /wallets page and (future) specialist_analyzer scoring.
# The table is agnostic of strategy: a wallet may appear in spec_ranking,
# scalper_pool, or both — strategies_active holds the context.

def upsert_wallet_profile(profile: dict) -> None:
    """Upsert a full wallet profile row. `profile` must contain `wallet`.

    If the DB rejects the row because a column doesn't exist (migration not
    applied yet), retry once with the unknown columns stripped. This makes
    v3.0 rollout resilient — the migration can be applied after deploy.
    """
    if not profile.get("wallet"):
        raise ValueError("upsert_wallet_profile: profile missing wallet")
    try:
        _db.upsert("wallet_profiles", profile, on_conflict="wallet")
    except Exception as e:
        msg = str(e)
        # Postgres "column X of relation Y does not exist" — retry without it
        import re
        m = re.search(r"column [\"']?([\w_]+)[\"']? of relation", msg)
        if m and m.group(1) in profile:
            stripped_col = m.group(1)
            cleaned = {k: v for k, v in profile.items() if k != stripped_col}
            logger.warning(
                f"upsert_wallet_profile {profile['wallet'][:10]}…: column "
                f"'{stripped_col}' missing — retrying without it. "
                f"Apply migration 013 to enable."
            )
            try:
                _db.upsert("wallet_profiles", cleaned, on_conflict="wallet")
                return
            except Exception as e2:
                logger.warning(f"upsert_wallet_profile retry failed: {e2}")
                return
        logger.warning(f"upsert_wallet_profile {profile['wallet'][:10]}…: {e}")


def get_wallet_profile(wallet: str) -> dict | None:
    client = _db.get_client()
    try:
        result = (
            client.table("wallet_profiles")
            .select("*")
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.debug(f"get_wallet_profile {wallet[:10]}: {e}")
        return None


def list_wallet_profiles(
    strategy: Optional[str] = None,
    limit: int = 50,
    order_by: str = "priority_score",
    desc: bool = True,
) -> list[dict]:
    """List enriched wallet profiles, optionally filtered by strategy.

    `strategy` matches against the TEXT[] column `strategies_active` via
    PostgREST's `cs` (contains) operator.
    """
    client = _db.get_client()
    q = client.table("wallet_profiles").select("*")
    if strategy:
        # PostgREST array containment: strategies_active @> '{SPECIALIST}'
        q = q.contains("strategies_active", [strategy])
    q = q.order(order_by, desc=desc).limit(limit)
    try:
        return q.execute().data or []
    except Exception as e:
        logger.warning(f"list_wallet_profiles strategy={strategy}: {e}")
        return []


def list_stale_wallet_profiles(
    stale_after_days: int = 7, batch_size: int = 20
) -> list[dict]:
    """Return wallets whose profile was enriched more than `stale_after_days`
    ago. Used by the enricher to pick next refresh candidates."""
    client = _db.get_client()
    cutoff = int(datetime.now(tz=timezone.utc).timestamp()) - stale_after_days * 86400
    try:
        return (
            client.table("wallet_profiles")
            .select("wallet, enriched_at, priority_score, strategies_active")
            .lt("enriched_at", cutoff)
            .order("enriched_at", desc=False)  # oldest first
            .limit(batch_size)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(f"list_stale_wallet_profiles: {e}")
        return []


def list_spec_ranking_addresses(run_id: Optional[str] = None) -> list[dict]:
    """Return `{wallet, universe, specialist_score, last_active_ts, is_bot}` for
    every specialist in spec_ranking. If run_id is given, only that run's rows.
    The enricher dedupes by wallet (keeping the highest specialist_score per wallet)."""
    client = _db.get_client()
    q = (
        client.table("spec_ranking")
        .select("wallet, universe, specialist_score, last_active_ts, is_bot")
    )
    if run_id:
        q = q.eq("run_id", run_id)
    try:
        return q.execute().data or []
    except Exception as e:
        logger.warning(f"list_spec_ranking_addresses: {e}")
        return []


def list_scalper_pool_addresses(run_id: str) -> list[dict]:
    """Return `{wallet_address, rank_position, status, sharpe_14d}` for the
    current scalper pool (run scoped)."""
    client = _db.get_client()
    try:
        return (
            client.table("scalper_pool")
            .select("wallet_address, rank_position, status, sharpe_14d")
            .eq("run_id", run_id)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(f"list_scalper_pool_addresses: {e}")
        return []


# ── Scalper V2 helpers ──────────────────────────────────────────────────────


def get_scalper_pool_entry(wallet: str, *, run_id: str) -> dict | None:
    """Single scalper_pool row for a wallet in a run."""
    client = _db.get_client()
    try:
        rows = (
            client.table("scalper_pool")
            .select("*")
            .eq("run_id", run_id)
            .eq("wallet_address", wallet)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"get_scalper_pool_entry: {e}")
        return None


def update_scalper_pool_fields(wallet: str, data: dict, *, run_id: str) -> None:
    """Update arbitrary columns on a scalper_pool row."""
    client = _db.get_client()
    try:
        client.table("scalper_pool").update(data).eq(
            "run_id", run_id
        ).eq("wallet_address", wallet).execute()
    except Exception as e:
        logger.warning(f"update_scalper_pool_fields: {e}")


def list_open_trades_for_titular(
    titular_wallet: str, *, run_id: str, is_shadow: bool = False
) -> list[dict]:
    """Open trades for a specific titular (source_wallet)."""
    client = _db.get_client()
    try:
        return (
            client.table("copy_trades")
            .select("id, position_usd, entry_price, outcome_token_id, market_type, metadata")
            .eq("run_id", run_id)
            .eq("strategy", "SCALPER")
            .eq("status", "OPEN")
            .eq("is_shadow", is_shadow)
            .eq("source_wallet", titular_wallet)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(f"list_open_trades_for_titular: {e}")
        return []


# ── Cooldown CRUD ───────────────────────────────────────────────────────────


def insert_cooldown(
    wallet: str,
    market_type: str,
    reason: str,
    expires_at: str,
    escalation_level: int = 1,
    metrics_at_removal: dict | None = None,
) -> None:
    """Insert a new cooldown. Deactivates any existing active cooldown for the
    same (wallet, market_type) first."""
    client = _db.get_client()
    try:
        # Deactivate existing
        client.table("scalper_cooldowns").update({"is_active": False}).eq(
            "wallet_address", wallet
        ).eq("market_type", market_type).eq("is_active", True).execute()
        # Insert new
        client.table("scalper_cooldowns").insert({
            "wallet_address": wallet,
            "market_type": market_type,
            "reason": reason,
            "expires_at": expires_at,
            "escalation_level": escalation_level,
            "is_active": True,
            "metrics_at_removal": metrics_at_removal,
        }).execute()
    except Exception as e:
        logger.warning(f"insert_cooldown: {e}")


def get_active_cooldown(wallet: str, market_type: str) -> dict | None:
    """Return the active cooldown for a (wallet, market_type), if any."""
    client = _db.get_client()
    try:
        rows = (
            client.table("scalper_cooldowns")
            .select("*")
            .eq("wallet_address", wallet)
            .eq("market_type", market_type)
            .eq("is_active", True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"get_active_cooldown: {e}")
        return None


def list_active_cooldowns() -> list[dict]:
    """All currently active cooldowns."""
    client = _db.get_client()
    try:
        return (
            client.table("scalper_cooldowns")
            .select("wallet_address, market_type, expires_at, escalation_level, reason")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(f"list_active_cooldowns: {e}")
        return []


def deactivate_cooldown(cooldown_id: str) -> None:
    client = _db.get_client()
    try:
        client.table("scalper_cooldowns").update(
            {"is_active": False}
        ).eq("id", cooldown_id).execute()
    except Exception as e:
        logger.warning(f"deactivate_cooldown: {e}")


def count_cooldown_history(wallet: str, market_type: str) -> int:
    """Count all cooldowns (active + expired) for a (wallet, market_type) pair.
    Used to determine escalation level."""
    client = _db.get_client()
    try:
        rows = (
            client.table("scalper_cooldowns")
            .select("id", count="exact")
            .eq("wallet_address", wallet)
            .eq("market_type", market_type)
            .execute()
        )
        return rows.count or 0
    except Exception as e:
        logger.warning(f"count_cooldown_history: {e}")
        return 0


# ── Scalper config CRUD ─────────────────────────────────────────────────────


def get_scalper_config(run_id: str) -> dict:
    """Return the scalper config dict for a run, or defaults."""
    client = _db.get_client()
    try:
        rows = (
            client.table("scalper_config")
            .select("config")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0]["config"] if rows else {}
    except Exception as e:
        logger.warning(f"get_scalper_config: {e}")
        return {}


def upsert_scalper_config(run_id: str, config: dict) -> None:
    client = _db.get_client()
    try:
        client.table("scalper_config").upsert(
            {"run_id": run_id, "config": config, "updated_at": "now()"},
            on_conflict="run_id",
        ).execute()
    except Exception as e:
        logger.warning(f"upsert_scalper_config: {e}")


# ── Roadmap snapshot ────────────────────────────────────────────────────────


def insert_roadmap_snapshot(content: dict, version: str | None = None) -> None:
    client = _db.get_client()
    try:
        client.table("roadmap_snapshots").insert({
            "content": content,
            "version": version,
        }).execute()
    except Exception as e:
        logger.warning(f"insert_roadmap_snapshot: {e}")


def get_latest_roadmap_snapshot() -> dict | None:
    client = _db.get_client()
    try:
        rows = (
            client.table("roadmap_snapshots")
            .select("*")
            .order("snapshot_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"get_latest_roadmap_snapshot: {e}")
        return None


# ── Eligible scalper candidates (wallet_profiles query) ─────────────────────


def list_eligible_scalper_candidates(
    cooldown_wallets: set[str] | None = None,
    min_confidence: list[str] | None = None,
    min_last_30d_trades: int = 5,
    limit: int = 100,
) -> list[dict]:
    """Fetch enriched wallet profiles eligible for scalper titular selection.

    Returns profiles with confidence HIGH/MEDIUM, recently active, not in
    cooldown set. Ordered by priority_score DESC.
    """
    if min_confidence is None:
        min_confidence = ["HIGH", "MEDIUM"]
    client = _db.get_client()
    try:
        q = (
            client.table("wallet_profiles")
            .select(
                "wallet, profile_confidence, type_hit_rates, type_profit_factors, "
                "type_trade_counts, type_sharpe_ratios, worst_30d_hit_rate, "
                "hit_rate_variance, momentum_score, sharpe_proxy, "
                "last_30d_trades, last_7d_trades, hit_rate_trend, "
                "best_type_hit_rate, typical_n_simultaneous, estimated_portfolio_usd, "
                "primary_archetype, rarity_tier"
            )
            .in_("profile_confidence", min_confidence)
            .gte("last_30d_trades", min_last_30d_trades)
            .order("priority_score", desc=True)
            .limit(limit)
        )
        rows = q.execute().data or []
        if cooldown_wallets:
            rows = [r for r in rows if r["wallet"] not in cooldown_wallets]
        return rows
    except Exception as e:
        logger.warning(f"list_eligible_scalper_candidates: {e}")
        return []
