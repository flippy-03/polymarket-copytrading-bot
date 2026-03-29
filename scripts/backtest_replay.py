"""
backtest_replay.py — Capa 2 del test suite

Replays all CLOSED trades from run_id=2 snapshot-by-snapshot using real
market_snapshots data, simulating position_manager logic:
  - RESOLUTION   (yes_price >= 0.97 or <= 0.03)
  - TRAILING_STOP (current_price <= entry * (1 - TRAILING_STOP_PCT))
  - TAKE_PROFIT   (current_price >= entry * (1 + TAKE_PROFIT_PCT))
  - TIMEOUT       (trade open > MAX_TRADE_DAYS)

Compares simulated close reason + exit price vs actual bot decisions.
Produces a JSON report to reports/backtest_replay_{timestamp}.json.

Usage:
    PYTHONPATH=. python scripts/backtest_replay.py [--run-id 2] [--output reports/]
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.db import supabase_client as db
from src.utils.config import TRAILING_STOP_PCT, TAKE_PROFIT_PCT

# Mirror position_manager constants exactly
MAX_TRADE_DAYS = 7
RESOLUTION_THRESHOLD = 0.97


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


def simulate_trade(trade: dict, snapshots: list) -> dict:
    """
    Simulate position_manager logic for one trade over its snapshots.
    Returns a dict with simulation results.
    """
    entry_price = float(trade["entry_price"])
    direction = trade["direction"]
    opened_at = trade.get("opened_at", "")

    sim_close_reason = None
    sim_exit_price = None
    sim_close_snapshot_at = None
    trigger_snapshot_idx = None
    peak_price = entry_price  # for reference

    for idx, snap in enumerate(snapshots):
        yes_price = snap.get("yes_price")
        if yes_price is None:
            continue

        yes_price = float(yes_price)
        current_price = _sim_current_price(yes_price, direction)
        peak_price = max(peak_price, current_price)

        # 1. Resolution check (always first, same priority as position_manager)
        resolved, yes_exit = _sim_is_resolved(yes_price)
        if resolved:
            exit_price = yes_exit if direction == "YES" else round(1 - yes_exit, 4)
            sim_close_reason = "RESOLUTION"
            sim_exit_price = round(exit_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            trigger_snapshot_idx = idx
            break

        # 2. Timeout
        if _sim_is_expired(opened_at, snap["snapshot_at"]):
            sim_close_reason = "TIMEOUT"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            trigger_snapshot_idx = idx
            break

        # 3. Trailing stop
        if current_price <= entry_price * (1 - TRAILING_STOP_PCT):
            sim_close_reason = "TRAILING_STOP"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            trigger_snapshot_idx = idx
            break

        # 4. Take profit
        if current_price >= entry_price * (1 + TAKE_PROFIT_PCT):
            sim_close_reason = "TAKE_PROFIT"
            sim_exit_price = round(current_price, 4)
            sim_close_snapshot_at = snap["snapshot_at"]
            trigger_snapshot_idx = idx
            break

    # If simulation never triggered a close, record as NO_TRIGGER
    if sim_close_reason is None:
        sim_close_reason = "NO_TRIGGER"
        if snapshots:
            last = snapshots[-1]
            yes_price = last.get("yes_price")
            if yes_price is not None:
                sim_exit_price = round(_sim_current_price(float(yes_price), direction), 4)
        sim_close_snapshot_at = snapshots[-1]["snapshot_at"] if snapshots else None

    # Simulated P&L
    shares = float(trade.get("shares", 0))
    position_usd = float(trade.get("position_usd", 0))
    sim_pnl_usd = None
    if sim_exit_price is not None and shares:
        sim_pnl_usd = round((sim_exit_price - entry_price) * shares, 2)

    # Agreement check
    actual_reason = trade.get("close_reason", "")
    actual_exit = float(trade["exit_price"]) if trade.get("exit_price") is not None else None
    actual_pnl = float(trade["pnl_usd"]) if trade.get("pnl_usd") is not None else None

    reason_match = sim_close_reason == actual_reason
    # Exit price agreement within $0.02 tolerance (snapshot timing jitter)
    price_match = (
        actual_exit is not None
        and sim_exit_price is not None
        and abs(sim_exit_price - actual_exit) <= 0.02
    )
    pnl_match = (
        actual_pnl is not None
        and sim_pnl_usd is not None
        and abs(sim_pnl_usd - actual_pnl) <= 0.50  # $0.50 tolerance
    )

    return {
        "trade_id": trade["id"],
        "direction": direction,
        "entry_price": entry_price,
        "opened_at": opened_at,
        "closed_at": trade.get("closed_at"),
        "n_snapshots": len(snapshots),
        "peak_price": round(peak_price, 4),
        # Actual
        "actual_close_reason": actual_reason,
        "actual_exit_price": actual_exit,
        "actual_pnl_usd": actual_pnl,
        # Simulated
        "sim_close_reason": sim_close_reason,
        "sim_exit_price": sim_exit_price,
        "sim_pnl_usd": sim_pnl_usd,
        "sim_close_snapshot_at": sim_close_snapshot_at,
        "sim_trigger_snapshot_idx": trigger_snapshot_idx,
        # Agreement
        "reason_match": reason_match,
        "price_match": price_match,
        "pnl_match": pnl_match,
        "agreement": reason_match and price_match,
    }


def fetch_snapshots_for_trade(client, market_id: str, opened_at: str, closed_at: str) -> list:
    """Fetch all snapshots for market_id between opened_at and closed_at, ordered ASC."""
    # Add a small buffer before opened_at to catch the entry snapshot
    try:
        opened_dt = datetime.fromisoformat(opened_at)
        if opened_dt.tzinfo is None:
            opened_dt = opened_dt.replace(tzinfo=timezone.utc)
        buffer_start = (opened_dt - timedelta(minutes=5)).isoformat()
    except Exception:
        buffer_start = opened_at

    result = (
        client.table("market_snapshots")
        .select("snapshot_at, yes_price")
        .eq("market_id", market_id)
        .gte("snapshot_at", buffer_start)
        .lte("snapshot_at", closed_at)
        .order("snapshot_at", desc=False)
        .execute()
    )
    return result.data or []


def run_backtest(run_id: int, output_dir: str) -> None:
    client = db.get_client()

    # 1. Get latest run_id if not specified explicitly
    port = (
        client.table("portfolio_state")
        .select("run_id, initial_capital, current_capital")
        .order("run_id", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not port:
        print("No portfolio_state found.")
        return
    if run_id == 0:
        run_id = port[0]["run_id"]
    initial_capital = float(port[0]["initial_capital"])

    print(f"Backtest replay — run_id={run_id}")

    # 2. Load all CLOSED trades for this run
    trades = (
        client.table("paper_trades")
        .select("*")
        .eq("status", "CLOSED")
        .eq("run_id", run_id)
        .order("closed_at", desc=False)
        .execute()
        .data
    )

    if not trades:
        print(f"No CLOSED trades found for run_id={run_id}.")
        return

    print(f"Found {len(trades)} closed trades. Processing...")

    # 3. Simulate each trade
    results = []
    for i, trade in enumerate(trades):
        trade_id_short = trade["id"][:8]
        market_id = trade["market_id"]
        opened_at = trade.get("opened_at") or ""
        closed_at = trade.get("closed_at") or ""

        if not opened_at or not closed_at:
            print(f"  [{i+1}/{len(trades)}] {trade_id_short}... SKIP — missing timestamps")
            results.append({
                "trade_id": trade["id"],
                "skip_reason": "missing_timestamps",
            })
            continue

        snapshots = fetch_snapshots_for_trade(client, market_id, opened_at, closed_at)
        result = simulate_trade(trade, snapshots)

        status = "OK" if result["agreement"] else "DIFF"
        pnl_diff = ""
        if result["actual_pnl_usd"] is not None and result["sim_pnl_usd"] is not None:
            diff = result["sim_pnl_usd"] - result["actual_pnl_usd"]
            pnl_diff = f" | P&L diff: ${diff:+.2f}"

        print(
            f"  [{i+1}/{len(trades)}] {trade_id_short}... [{status}] "
            f"{trade['direction']} entry={trade['entry_price']} "
            f"actual={result['actual_close_reason']}/{result['actual_exit_price']} "
            f"sim={result['sim_close_reason']}/{result['sim_exit_price']} "
            f"snaps={result['n_snapshots']}{pnl_diff}"
        )
        results.append(result)

    # 4. Summary stats
    valid = [r for r in results if "skip_reason" not in r]
    agreements = sum(1 for r in valid if r.get("agreement"))
    reason_matches = sum(1 for r in valid if r.get("reason_match"))
    no_trigger = sum(1 for r in valid if r.get("sim_close_reason") == "NO_TRIGGER")
    no_snapshots = sum(1 for r in valid if r.get("n_snapshots", 0) == 0)

    sim_total_pnl = sum(r["sim_pnl_usd"] for r in valid if r.get("sim_pnl_usd") is not None)
    actual_total_pnl = sum(r["actual_pnl_usd"] for r in valid if r.get("actual_pnl_usd") is not None)

    summary = {
        "run_id": run_id,
        "initial_capital": initial_capital,
        "total_trades": len(trades),
        "valid_trades": len(valid),
        "agreements": agreements,
        "agreement_rate": round(agreements / len(valid), 4) if valid else 0,
        "reason_matches": reason_matches,
        "reason_match_rate": round(reason_matches / len(valid), 4) if valid else 0,
        "no_trigger_count": no_trigger,
        "no_snapshots_count": no_snapshots,
        "actual_total_pnl": round(actual_total_pnl, 2),
        "sim_total_pnl": round(sim_total_pnl, 2),
        "pnl_delta": round(sim_total_pnl - actual_total_pnl, 2),
        "params": {
            "TRAILING_STOP_PCT": TRAILING_STOP_PCT,
            "TAKE_PROFIT_PCT": TAKE_PROFIT_PCT,
            "MAX_TRADE_DAYS": MAX_TRADE_DAYS,
            "RESOLUTION_THRESHOLD": RESOLUTION_THRESHOLD,
        },
    }

    print(f"\n=== Backtest Summary ===")
    print(f"  Trades:         {summary['valid_trades']} valid / {summary['total_trades']} total")
    print(f"  Agreement:      {agreements}/{len(valid)} ({summary['agreement_rate']*100:.0f}%)")
    print(f"  Reason match:   {reason_matches}/{len(valid)} ({summary['reason_match_rate']*100:.0f}%)")
    print(f"  No trigger:     {no_trigger} (insufficient snapshots or no close condition met)")
    print(f"  No snapshots:   {no_snapshots}")
    print(f"  Actual P&L:     ${actual_total_pnl:+.2f}")
    print(f"  Simulated P&L:  ${sim_total_pnl:+.2f}")
    print(f"  P&L delta:      ${summary['pnl_delta']:+.2f}")

    # 5. Highlight discrepancies
    discrepancies = [r for r in valid if not r.get("agreement") and r.get("sim_close_reason") != "NO_TRIGGER"]
    if discrepancies:
        print(f"\n=== Discrepancies ({len(discrepancies)}) ===")
        for r in discrepancies:
            print(
                f"  {r['trade_id'][:8]}... {r['direction']} entry={r['entry_price']} | "
                f"actual: {r['actual_close_reason']} @ {r['actual_exit_price']} (${r['actual_pnl_usd']:+.2f}) | "
                f"sim: {r['sim_close_reason']} @ {r['sim_exit_price']} (${r['sim_pnl_usd']:+.2f})"
            )

    # 6. Write JSON report
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(output_dir, f"backtest_replay_{ts}.json")
    report = {"summary": summary, "trades": results}
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest replay — position_manager validation")
    parser.add_argument("--run-id", type=int, default=0, help="run_id to replay (0=latest)")
    parser.add_argument("--output", type=str, default="reports", help="Output directory for JSON report")
    args = parser.parse_args()

    run_backtest(run_id=args.run_id, output_dir=args.output)
