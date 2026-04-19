"""Shadow validation evaluator.

Runs on a schedule (hourly or via the 6h degradation cron). For every
scalper_pool entry whose shadow_validation_until has expired and that is
still validation_outcome='PENDING', computes paper performance over the
window and either PROMOTES the titular (clearing the shadow flag so future
trades go real) or REJECTS them (status → POOL, added to cooldown).

Criteria (all must hold to promote):
  - >= C.SHADOW_MIN_TRADES closed shadow trades in the window
  - paper WR >= C.SHADOW_PAPER_WR_FLOOR
  - paper PnL / total_size >= C.SHADOW_PAPER_PNL_FLOOR_PCT
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.db import supabase_client as _db
from src.strategies.common import config as C
from src.utils.logger import logger


def _compute_paper_metrics(
    wallet: str, run_id: str, window_start_iso: str
) -> Optional[dict]:
    """Aggregate paper performance for a wallet's shadow trades since the
    window start. Returns {n_closed, wins, total_size, total_pnl} or None
    on error.
    """
    try:
        client = _db.get_client()
        rows = (
            client.table("copy_trades")
            .select("pnl_usd,position_usd,status")
            .eq("run_id", run_id)
            .eq("strategy", "SCALPER")
            .eq("source_wallet", wallet)
            .eq("is_shadow", True)
            .eq("status", "CLOSED")
            .gte("opened_at", window_start_iso)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"shadow_validator fetch paper metrics {wallet[:10]}: {e}")
        return None

    if not rows:
        return {"n_closed": 0, "wins": 0, "total_size": 0.0, "total_pnl": 0.0}

    n_closed = len(rows)
    wins = sum(1 for r in rows if float(r.get("pnl_usd") or 0) > 0)
    total_size = sum(float(r.get("position_usd") or 0) for r in rows)
    total_pnl = sum(float(r.get("pnl_usd") or 0) for r in rows)
    return {
        "n_closed": n_closed,
        "wins": wins,
        "total_size": total_size,
        "total_pnl": total_pnl,
    }


def _promote(wallet: str, run_id: str, metrics: dict) -> None:
    client = _db.get_client()
    client.table("scalper_pool").update(
        {"validation_outcome": "PROMOTED", "shadow_validation_until": None}
    ).eq("run_id", run_id).eq("wallet_address", wallet).execute()
    logger.info(
        f"[shadow_validator] PROMOTED {wallet[:10]} "
        f"n={metrics['n_closed']} wr={metrics['wins']}/{metrics['n_closed']} "
        f"pnl=${metrics['total_pnl']:.2f}"
    )


def _reject(wallet: str, run_id: str, metrics: dict, reason: str) -> None:
    client = _db.get_client()
    client.table("scalper_pool").update(
        {
            "validation_outcome": "REJECTED",
            "status": "POOL",
        }
    ).eq("run_id", run_id).eq("wallet_address", wallet).execute()
    logger.warning(
        f"[shadow_validator] REJECTED {wallet[:10]} reason={reason} "
        f"n={metrics['n_closed']} pnl=${metrics['total_pnl']:.2f}"
    )


def evaluate(run_id: str) -> dict:
    """Main entry point. Iterates PENDING entries whose window has expired.

    Returns summary counts: {evaluated, promoted, rejected, still_pending}.
    """
    client = _db.get_client()
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    try:
        pending = (
            client.table("scalper_pool")
            .select("wallet_address,shadow_validation_until,entered_at")
            .eq("run_id", run_id)
            .eq("validation_outcome", "PENDING")
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"[shadow_validator] fetch pending failed: {e}")
        return {"evaluated": 0, "promoted": 0, "rejected": 0, "still_pending": 0}

    summary = {"evaluated": 0, "promoted": 0, "rejected": 0, "still_pending": 0}

    for row in pending:
        wallet = row["wallet_address"]
        until = row.get("shadow_validation_until")
        if not until:
            continue
        deadline = datetime.fromisoformat(until.replace("Z", "+00:00"))
        if datetime.now(tz=timezone.utc) < deadline:
            summary["still_pending"] += 1
            continue

        window_start = row.get("entered_at") or until  # entered_at is ISO
        m = _compute_paper_metrics(wallet, run_id, window_start)
        if m is None:
            continue
        summary["evaluated"] += 1

        if m["n_closed"] < C.SHADOW_MIN_TRADES:
            _reject(wallet, run_id, m, reason=f"insufficient_trades={m['n_closed']}")
            summary["rejected"] += 1
            continue

        wr = m["wins"] / m["n_closed"] if m["n_closed"] else 0.0
        if wr < C.SHADOW_PAPER_WR_FLOOR:
            _reject(wallet, run_id, m, reason=f"wr={wr:.2f}")
            summary["rejected"] += 1
            continue

        pnl_ratio = (
            m["total_pnl"] / m["total_size"] if m["total_size"] > 0 else 0.0
        )
        if pnl_ratio < C.SHADOW_PAPER_PNL_FLOOR_PCT:
            _reject(wallet, run_id, m, reason=f"pnl_ratio={pnl_ratio:.3f}")
            summary["rejected"] += 1
            continue

        _promote(wallet, run_id, m)
        summary["promoted"] += 1

    logger.info(f"[shadow_validator] run={run_id[:8]} summary={summary}")
    return summary
