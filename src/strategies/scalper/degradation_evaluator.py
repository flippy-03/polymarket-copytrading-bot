"""Degradation evaluator for SCALPER titulars.

Per niche_specialist_engine.html §09, runs on a cron (default every 6h)
and applies Layer 1 / 1b policies per titular:

  - Layer 1 (pause):
      pnl_7d_pct <= -12%  OR  win_rate_last_15 < 0.62
  - Layer 1b (reduce sizing to 0.5x):
      0.62 <= win_rate_last_15 < 0.65
  - Recovery (restore sizing to 1.0x):
      win_rate_last_10 >= 0.70  AND  currently reduced

Actions are idempotent: running the evaluator twice back-to-back produces
no extra state change. Every transition writes a row to risk_events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.db import supabase_client as _db
from src.strategies.common import config as C
from src.utils.logger import logger


def _recent_closed(wallet: str, run_id: str, window_days: int) -> list[dict]:
    """Real closed SCALPER trades for this wallet in the window."""
    since = (
        datetime.now(tz=timezone.utc) - timedelta(days=window_days)
    ).isoformat()
    client = _db.get_client()
    try:
        rows = (
            client.table("copy_trades")
            .select("pnl_usd,pnl_pct,position_usd,closed_at")
            .eq("run_id", run_id)
            .eq("strategy", "SCALPER")
            .eq("source_wallet", wallet)
            .eq("is_shadow", False)
            .eq("status", "CLOSED")
            .gte("closed_at", since)
            .order("closed_at", desc=True)
            .execute()
            .data
        ) or []
        return rows
    except Exception as e:
        logger.warning(f"degradation_evaluator fetch {wallet[:10]}: {e}")
        return []


def _compute_metrics(rows: list[dict], allocated_capital: float) -> dict:
    """Build the metrics tuple used by the decision rules.

    pnl_7d_pct is the net PnL over the window divided by allocated_capital;
    WR15 / WR10 count ordered by closed_at DESC.
    """
    sorted_rows = rows  # already DESC by query
    pnl_7d = sum(float(r.get("pnl_usd") or 0) for r in sorted_rows)
    pnl_7d_pct = pnl_7d / allocated_capital if allocated_capital > 0 else 0.0

    last15 = sorted_rows[:15]
    last10 = sorted_rows[:10]
    wr_15 = (
        sum(1 for r in last15 if float(r.get("pnl_usd") or 0) > 0) / len(last15)
        if last15 else None
    )
    wr_10 = (
        sum(1 for r in last10 if float(r.get("pnl_usd") or 0) > 0) / len(last10)
        if last10 else None
    )
    return {
        "pnl_7d": pnl_7d,
        "pnl_7d_pct": pnl_7d_pct,
        "n_total": len(sorted_rows),
        "wr_15": wr_15,
        "wr_10": wr_10,
    }


def _log_event(
    *,
    run_id: str,
    wallet: str,
    layer: str,
    action: str,
    metric: str,
    value: Optional[float],
    notes: str = "",
) -> None:
    client = _db.get_client()
    try:
        client.table("risk_events").insert({
            "run_id": run_id,
            "layer": layer,
            "scope": "titular",
            "wallet": wallet,
            "action": action,
            "trigger_metric": metric,
            "trigger_value": value,
            "notes": notes,
        }).execute()
    except Exception as e:
        logger.debug(f"risk_events insert failed: {e}")


def _apply_pause(run_id: str, wallet: str, metric: str, value: float) -> None:
    client = _db.get_client()
    client.table("scalper_pool").update({
        "per_trader_is_broken": True,
    }).eq("run_id", run_id).eq("wallet_address", wallet).execute()
    _log_event(
        run_id=run_id, wallet=wallet, layer="1", action="pause",
        metric=metric, value=value,
    )
    logger.warning(
        f"[degradation] PAUSE {wallet[:10]} metric={metric} value={value:.3f}"
    )


def _apply_sizing_multiplier(
    run_id: str, wallet: str, mult: float, metric: str, value: Optional[float],
    layer: str, action: str,
) -> None:
    client = _db.get_client()
    client.table("scalper_pool").update({
        "sizing_multiplier": mult,
    }).eq("run_id", run_id).eq("wallet_address", wallet).execute()
    _log_event(
        run_id=run_id, wallet=wallet, layer=layer, action=action,
        metric=metric, value=value,
    )
    logger.info(
        f"[degradation] {action.upper()} {wallet[:10]} mult={mult} "
        f"metric={metric} value={value}"
    )


def evaluate(run_id: str) -> dict:
    """Run one pass of the degradation rules for all active titulars in the run.

    Returns a summary dict with counts.
    """
    client = _db.get_client()
    try:
        actives = (
            client.table("scalper_pool")
            .select("wallet_address,capital_allocated_usd,sizing_multiplier,"
                    "per_trader_is_broken,validation_outcome,shadow_validation_until")
            .eq("run_id", run_id)
            .eq("status", "ACTIVE_TITULAR")
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"degradation_evaluator fetch actives failed: {e}")
        return {"evaluated": 0, "paused": 0, "reduced": 0, "restored": 0}

    summary = {"evaluated": 0, "paused": 0, "reduced": 0, "restored": 0, "skipped": 0}

    for entry in actives:
        wallet = entry["wallet_address"]

        # Skip titulars still in shadow window — those go through shadow_validator.
        until = entry.get("shadow_validation_until")
        outcome = entry.get("validation_outcome")
        if outcome == "PENDING" and until:
            deadline = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) < deadline:
                summary["skipped"] += 1
                continue

        # Already broken — degradation evaluator doesn't un-break. That's a
        # manual-review path (or the next rotation cycle replaces them).
        if entry.get("per_trader_is_broken"):
            summary["skipped"] += 1
            continue

        rows = _recent_closed(wallet, run_id, C.DEGRADATION_WINDOW_DAYS)
        if not rows:
            summary["skipped"] += 1
            continue

        allocated = float(entry.get("capital_allocated_usd") or 0)
        if allocated <= 0:
            # Fall back to a nominal $1000 — avoids div-by-zero and is only
            # used for the pnl_7d_pct metric which becomes proportional.
            allocated = float(C.SCALPER_INITIAL_CAPITAL)

        m = _compute_metrics(rows, allocated)
        summary["evaluated"] += 1

        # Layer 1 — hard pause
        if m["pnl_7d_pct"] <= C.DEGRADATION_PNL_7D_PAUSE_PCT:
            _apply_pause(run_id, wallet, "pnl_7d_pct", m["pnl_7d_pct"])
            summary["paused"] += 1
            continue

        if m["wr_15"] is not None and m["wr_15"] < C.DEGRADATION_WR15_PAUSE:
            _apply_pause(run_id, wallet, "wr_15", m["wr_15"])
            summary["paused"] += 1
            continue

        current_mult = float(entry.get("sizing_multiplier") or 1.0)

        # Recovery — restore before considering reduction
        if (
            current_mult < 1.0
            and m["wr_10"] is not None
            and m["wr_10"] >= C.DEGRADATION_RECOVERY_WR10
        ):
            _apply_sizing_multiplier(
                run_id, wallet, mult=1.0, metric="wr_10", value=m["wr_10"],
                layer="1b", action="restore",
            )
            summary["restored"] += 1
            continue

        # Layer 1b — reduce to 50%
        if (
            m["wr_15"] is not None
            and m["wr_15"] < C.DEGRADATION_WR15_REDUCE
            and current_mult > C.DEGRADATION_SIZING_MULT_REDUCED
        ):
            _apply_sizing_multiplier(
                run_id, wallet,
                mult=C.DEGRADATION_SIZING_MULT_REDUCED,
                metric="wr_15", value=m["wr_15"],
                layer="1b", action="reduce_50",
            )
            summary["reduced"] += 1
            continue

    logger.info(f"[degradation_evaluator] run={run_id[:8]} summary={summary}")
    return summary


if __name__ == "__main__":
    # CLI entry point: python -m src.strategies.scalper.degradation_evaluator
    # Schedule this every DEGRADATION_EVAL_HOURS via systemd timer or cron.
    from src.strategies.common import db as _cdb
    run_id = _cdb.get_active_run("SCALPER")
    if not run_id:
        logger.warning("no active SCALPER run; exiting")
        raise SystemExit(0)
    # Also run the shadow validator in the same pass — they complement.
    from src.strategies.scalper import shadow_validator
    shadow_validator.evaluate(run_id)
    evaluate(run_id)
