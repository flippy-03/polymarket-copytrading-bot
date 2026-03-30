"""
shadow_portfolio.py — Signal Quality Retrospective

Simulates what would have happened if every EXPIRED signal had been executed.
Compares the "shadow portfolio" (all signals) vs actual portfolio (executed only)
to answer: are we discarding good signals? Should we increase MAX_OPEN_POSITIONS?

Methodology:
  - For each EXPIRED signal: simulate position_manager logic snapshot-by-snapshot
    using price_at_signal as entry, same stop/TP/timeout/resolution rules
  - For each EXECUTED signal: load actual trade outcome for baseline comparison
  - Report: shadow WR, shadow P&L, vs actual WR, actual P&L

Usage:
    PYTHONPATH=. python scripts/shadow_portfolio.py [--output reports/]
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.db import supabase_client as db
from src.utils.config import (
    TRAILING_STOP_PCT,
    TAKE_PROFIT_PCT,
    KELLY_FRACTION,
    MAX_POSITION_SIZE_PCT,
    INITIAL_CAPITAL,
)

MAX_TRADE_DAYS = 7
RESOLUTION_THRESHOLD = 0.97


# ── Simulation helpers (mirror position_manager exactly) ─────────────────────

def _sim_current_price(yes_price: float, direction: str) -> float:
    return yes_price if direction == "YES" else round(1 - yes_price, 4)


def _sim_is_resolved(yes_price: float) -> tuple[bool, float | None]:
    if yes_price >= RESOLUTION_THRESHOLD:
        return True, 1.0
    if yes_price <= (1 - RESOLUTION_THRESHOLD):
        return True, 0.0
    return False, None


def _sim_is_expired(opened_at_str: str, snapshot_at_str: str) -> bool:
    try:
        opened = datetime.fromisoformat(opened_at_str)
        snap = datetime.fromisoformat(snapshot_at_str)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        if snap.tzinfo is None:
            snap = snap.replace(tzinfo=timezone.utc)
        return snap > opened + timedelta(days=MAX_TRADE_DAYS)
    except Exception:
        return False


def _kelly_size(confidence: float, entry_price: float, capital: float) -> float:
    if entry_price <= 0 or entry_price >= 1:
        return 0.0
    odds = (1 / entry_price) - 1
    edge = confidence - (1 - confidence) / odds if odds > 0 else 0
    if edge <= 0:
        return 0.0
    kelly = edge / odds
    half_kelly = kelly * KELLY_FRACTION
    max_size = capital * MAX_POSITION_SIZE_PCT
    return round(min(half_kelly * capital, max_size), 2)


def simulate_signal(signal: dict, snapshots: list) -> dict:
    """Simulate position_manager for a single signal using its price_at_signal as entry."""
    direction = signal["direction"]
    yes_price_at_signal = float(signal["price_at_signal"])
    entry_price = yes_price_at_signal if direction == "YES" else round(1 - yes_price_at_signal, 4)
    created_at = signal["created_at"]
    confidence = float(signal.get("confidence") or 0.55)

    position_usd = _kelly_size(confidence, entry_price, INITIAL_CAPITAL)
    shares = round(position_usd / entry_price, 2) if entry_price > 0 else 0

    sim_close_reason = None
    sim_exit_price = None
    sim_close_snapshot_at = None
    peak_price = entry_price
    min_price = entry_price

    for idx, snap in enumerate(snapshots):
        yes_p = snap.get("yes_price")
        if yes_p is None:
            continue
        yes_p = float(yes_p)
        current_price = _sim_current_price(yes_p, direction)
        peak_price = max(peak_price, current_price)
        min_price = min(min_price, current_price)

        # 1. Resolution
        resolved, yes_exit = _sim_is_resolved(yes_p)
        if resolved:
            exit_p = yes_exit if direction == "YES" else round(1 - yes_exit, 4)
            sim_close_reason = "RESOLUTION"
            sim_exit_price = round(exit_p, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            break

        # 2. Timeout
        if _sim_is_expired(created_at, snap["snapshot_at"]):
            sim_close_reason = "TIMEOUT"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            break

        # 3. Trailing stop
        if current_price <= entry_price * (1 - TRAILING_STOP_PCT):
            sim_close_reason = "TRAILING_STOP"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            break

        # 4. Take profit
        if current_price >= entry_price * (1 + TAKE_PROFIT_PCT):
            sim_close_reason = "TAKE_PROFIT"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            break

    if sim_close_reason is None:
        sim_close_reason = "NO_TRIGGER"
        if snapshots:
            last_yes = snapshots[-1].get("yes_price")
            if last_yes is not None:
                sim_exit_price = round(_sim_current_price(float(last_yes), direction), 4)
        sim_close_snapshot_at = snapshots[-1]["snapshot_at"] if snapshots else None

    sim_pnl_usd = None
    sim_pnl_pct = None
    if sim_exit_price is not None and shares:
        sim_pnl_usd = round((sim_exit_price - entry_price) * shares, 2)
        sim_pnl_pct = round((sim_exit_price - entry_price) / entry_price, 4) if entry_price else 0

    # Hold time in hours
    hold_hours = None
    if sim_close_snapshot_at and created_at:
        try:
            t0 = datetime.fromisoformat(created_at)
            t1 = datetime.fromisoformat(sim_close_snapshot_at)
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            if t1.tzinfo is None:
                t1 = t1.replace(tzinfo=timezone.utc)
            hold_hours = round((t1 - t0).total_seconds() / 3600, 1)
        except Exception:
            pass

    return {
        "signal_id": signal["id"],
        "market_id": signal["market_id"],
        "direction": direction,
        "entry_price": entry_price,
        "yes_price_at_signal": yes_price_at_signal,
        "confidence": confidence,
        "total_score": signal.get("total_score"),
        "divergence_score": signal.get("divergence_score"),
        "momentum_score": signal.get("momentum_score"),
        "created_at": created_at,
        "position_usd": position_usd,
        "shares": shares,
        "n_snapshots": len(snapshots),
        "peak_price": round(peak_price, 4),
        "min_price": round(min_price, 4),
        "sim_close_reason": sim_close_reason,
        "sim_exit_price": sim_exit_price,
        "sim_pnl_usd": sim_pnl_usd,
        "sim_pnl_pct": sim_pnl_pct,
        "sim_close_snapshot_at": sim_close_snapshot_at,
        "hold_hours": hold_hours,
        "win": sim_pnl_usd is not None and sim_pnl_usd > 0,
    }


def fetch_snapshots(client, market_id: str, from_dt: str, days: int = MAX_TRADE_DAYS) -> list:
    try:
        t0 = datetime.fromisoformat(from_dt)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        t1 = (t0 + timedelta(days=days)).isoformat()
        # Small buffer before signal to catch first datapoint
        t0_buf = (t0 - timedelta(minutes=5)).isoformat()
    except Exception:
        t0_buf = from_dt
        t1 = from_dt

    result = (
        client.table("market_snapshots")
        .select("snapshot_at, yes_price")
        .eq("market_id", market_id)
        .gte("snapshot_at", t0_buf)
        .lte("snapshot_at", t1)
        .order("snapshot_at", desc=False)
        .execute()
    )
    return result.data or []


def _stats(results: list) -> dict:
    valid = [r for r in results if r.get("sim_pnl_usd") is not None and r.get("sim_close_reason") != "NO_TRIGGER"]
    no_trigger = [r for r in results if r.get("sim_close_reason") == "NO_TRIGGER"]
    no_snaps = [r for r in results if r.get("n_snapshots", 0) == 0]
    wins = [r for r in valid if r.get("win")]
    losses = [r for r in valid if not r.get("win")]
    total_pnl = sum(r["sim_pnl_usd"] for r in valid)
    avg_hold = (
        round(sum(r["hold_hours"] for r in valid if r.get("hold_hours")) / len(valid), 1)
        if valid else None
    )
    directions = {}
    for d in ["YES", "NO"]:
        dv = [r for r in valid if r["direction"] == d]
        dw = [r for r in dv if r.get("win")]
        directions[d] = {
            "count": len(dv),
            "wins": len(dw),
            "win_rate": round(len(dw) / len(dv), 3) if dv else None,
            "total_pnl": round(sum(r["sim_pnl_usd"] for r in dv), 2),
        }
    close_reasons = {}
    for r in valid:
        reason = r.get("sim_close_reason", "UNKNOWN")
        close_reasons[reason] = close_reasons.get(reason, 0) + 1

    return {
        "total": len(results),
        "valid": len(valid),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(valid), 3) if valid else None,
        "total_pnl_usd": round(total_pnl, 2),
        "avg_hold_hours": avg_hold,
        "no_trigger": len(no_trigger),
        "no_snapshots": len(no_snaps),
        "by_direction": directions,
        "by_close_reason": close_reasons,
    }


def run_shadow_portfolio(output_dir: str) -> None:
    client = db.get_client()

    # Load all signals
    all_signals = (
        client.table("signals")
        .select("*")
        .order("created_at", desc=False)
        .execute()
        .data
    )

    expired = [s for s in all_signals if s["status"] == "EXPIRED"]
    executed = [s for s in all_signals if s["status"] == "EXECUTED"]

    print(f"Signals — EXPIRED: {len(expired)} | EXECUTED: {len(executed)} | Total: {len(all_signals)}")

    # ── SECTION 1: Simulate EXPIRED signals ──────────────────────────────────
    print(f"\nSimulating {len(expired)} EXPIRED signals...")
    shadow_results = []
    for i, sig in enumerate(expired):
        mid = sig["market_id"]
        snaps = fetch_snapshots(client, mid, sig["created_at"])
        result = simulate_signal(sig, snaps)
        status = "W" if result.get("win") else ("?" if result["sim_close_reason"] == "NO_TRIGGER" else "L")
        print(
            f"  [{i+1}/{len(expired)}] [{status}] {sig['direction']} "
            f"entry={result['entry_price']:.3f} "
            f"→ {result['sim_close_reason']} @ {result['sim_exit_price']} "
            f"P&L=${result['sim_pnl_usd']:+.2f}" if result['sim_pnl_usd'] is not None
            else f"  [{i+1}/{len(expired)}] [?] {sig['direction']} entry={result['entry_price']:.3f} → NO_TRIGGER (snaps={result['n_snapshots']})"
        )
        shadow_results.append(result)

    # ── SECTION 2: Load EXECUTED signal outcomes ─────────────────────────────
    print(f"\nLoading {len(executed)} EXECUTED signal outcomes...")
    executed_results = []
    for sig in executed:
        trade = (
            client.table("paper_trades")
            .select("direction, entry_price, exit_price, pnl_usd, pnl_pct, close_reason, opened_at, closed_at, shares, position_usd")
            .eq("signal_id", sig["id"])
            .execute()
            .data
        )
        if not trade:
            continue
        t = trade[0]
        hold_hours = None
        if t.get("opened_at") and t.get("closed_at"):
            try:
                t0 = datetime.fromisoformat(t["opened_at"])
                t1 = datetime.fromisoformat(t["closed_at"])
                if t0.tzinfo is None: t0 = t0.replace(tzinfo=timezone.utc)
                if t1.tzinfo is None: t1 = t1.replace(tzinfo=timezone.utc)
                hold_hours = round((t1 - t0).total_seconds() / 3600, 1)
            except Exception:
                pass
        executed_results.append({
            "signal_id": sig["id"],
            "market_id": sig["market_id"],
            "direction": t["direction"],
            "entry_price": float(t["entry_price"]),
            "exit_price": float(t["exit_price"]) if t.get("exit_price") else None,
            "pnl_usd": float(t["pnl_usd"]) if t.get("pnl_usd") is not None else None,
            "pnl_pct": float(t["pnl_pct"]) if t.get("pnl_pct") is not None else None,
            "close_reason": t.get("close_reason"),
            "hold_hours": hold_hours,
            "confidence": float(sig.get("confidence") or 0.55),
            "total_score": sig.get("total_score"),
            "win": float(t["pnl_usd"]) > 0 if t.get("pnl_usd") is not None else None,
            "status": "CLOSED" if t.get("close_reason") else "OPEN",
        })

    # ── SECTION 3: Stats ─────────────────────────────────────────────────────
    shadow_stats = _stats(shadow_results)

    # Actual stats from executed trades (closed only)
    closed_executed = [r for r in executed_results if r["status"] == "CLOSED" and r["pnl_usd"] is not None]
    actual_wins = [r for r in closed_executed if r.get("win")]
    actual_pnl = sum(r["pnl_usd"] for r in closed_executed)
    actual_hold = (
        round(sum(r["hold_hours"] for r in closed_executed if r.get("hold_hours")) / len(closed_executed), 1)
        if closed_executed else None
    )
    actual_stats = {
        "total": len(executed_results),
        "closed": len(closed_executed),
        "wins": len(actual_wins),
        "losses": len(closed_executed) - len(actual_wins),
        "win_rate": round(len(actual_wins) / len(closed_executed), 3) if closed_executed else None,
        "total_pnl_usd": round(actual_pnl, 2),
        "avg_hold_hours": actual_hold,
    }

    # ── SECTION 4: Print comparison ──────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  SIGNAL QUALITY RETROSPECTIVE")
    print(f"{'='*55}")
    print(f"  {'':30} {'SHADOW':>10} {'ACTUAL':>10}")
    print(f"  {'─'*50}")
    print(f"  {'Signals/Trades':30} {shadow_stats['valid']:>10} {actual_stats['closed']:>10}")
    print(f"  {'Win rate':30} {(shadow_stats['win_rate'] or 0)*100:>9.0f}% {(actual_stats['win_rate'] or 0)*100:>9.0f}%")
    print(f"  {'Total P&L (simulated $1000 base)':30} ${shadow_stats['total_pnl_usd']:>+9.2f} ${actual_stats['total_pnl_usd']:>+9.2f}")
    print(f"  {'Avg hold time (hours)':30} {str(shadow_stats['avg_hold_hours'] or '-'):>10} {str(actual_stats['avg_hold_hours'] or '-'):>10}")
    print(f"  {'No data (no snapshots)':30} {shadow_stats['no_snapshots']:>10} {'—':>10}")
    print(f"  {'No trigger (data ends early)':30} {shadow_stats['no_trigger']:>10} {'—':>10}")

    print(f"\n  Shadow close reasons: {shadow_stats['by_close_reason']}")
    print(f"\n  Shadow by direction:")
    for d, dstats in shadow_stats["by_direction"].items():
        if dstats["count"] > 0:
            print(f"    {d}: {dstats['wins']}/{dstats['count']} wins ({(dstats['win_rate'] or 0)*100:.0f}%) | P&L ${dstats['total_pnl']:+.2f}")

    # ── SECTION 5: Verdict ───────────────────────────────────────────────────
    print(f"\n  {'─'*50}")
    sw = shadow_stats["win_rate"] or 0
    aw = actual_stats["win_rate"] or 0
    delta = sw - aw
    if abs(delta) < 0.05:
        verdict = "CONSISTENT — signals are uniformly good. Position limit safe to raise."
    elif delta > 0.05:
        verdict = f"SHADOW BETTER (+{delta*100:.0f}pp) — discarded signals are good. Raise MAX_OPEN_POSITIONS."
    else:
        verdict = f"ACTUAL BETTER ({delta*100:.0f}pp) — execution filter adds value. Keep position limit."
    print(f"  Verdict: {verdict}")
    print(f"{'='*55}")

    # ── SECTION 6: Save JSON ─────────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(output_dir, f"shadow_portfolio_{ts}.json")
    report = {
        "shadow_stats": shadow_stats,
        "actual_stats": actual_stats,
        "verdict": verdict,
        "shadow_trades": shadow_results,
        "actual_trades": executed_results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shadow portfolio — signal quality retrospective")
    parser.add_argument("--output", type=str, default="reports", help="Output directory")
    args = parser.parse_args()
    run_shadow_portfolio(output_dir=args.output)
