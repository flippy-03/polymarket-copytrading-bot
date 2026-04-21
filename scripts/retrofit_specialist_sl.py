"""Retrofit SPECIALIST real trades that closed deeper than their
universe-configured sl_pct.

Context: without the Gamma price fallback (commit yy...yy), the CLOB
orderbook occasionally stopped returning prices for 30-90 min near game
resolution. SL never triggered on the way down; when a price finally
returned (or the market resolved), the loss was already far past the
threshold. Now that the fallback exists, future trades close at their
configured SL. Clean up past data so the backtest reflects the corrected
behaviour.

Criterion: for any closed real SPECIALIST trade whose pnl_pct is deeper
than its universe's sl_pct, snap exit_price to entry * (1 + sl_pct),
pnl to position_usd * sl_pct, close_reason = 'STOP_LOSS_RETROFIT'.
Portfolio current_capital is reconciled at the end.

DRY-RUN by default; --apply to commit.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db
from src.strategies.common import config as C


def universe_sl(universe: str | None) -> float | None:
    if not universe:
        return None
    cfg = C.SPECIALIST_UNIVERSES.get(universe, {})
    return cfg.get("sl_pct")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = _db.get_client()

    # Find the active SPECIALIST run (v3.0)
    runs = (
        client.table("runs")
        .select("id,version")
        .eq("strategy", "SPECIALIST")
        .eq("status", "ACTIVE")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
        .data
    ) or []
    if not runs:
        print("No active SPECIALIST run")
        sys.exit(1)
    run_id = runs[0]["id"]
    print(f"SPECIALIST run: {run_id[:8]}  version={runs[0]['version']}")

    trades = (
        client.table("copy_trades")
        .select("id,market_question,direction,entry_price,exit_price,position_usd,"
                "pnl_usd,pnl_pct,close_reason,opened_at,closed_at,metadata")
        .eq("run_id", run_id)
        .eq("strategy", "SPECIALIST")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .execute()
        .data
    ) or []
    print(f"Closed real trades: {len(trades)}\n")

    to_fix = []
    for t in trades:
        pnl_pct = float(t.get("pnl_pct") or 0)
        md = t.get("metadata") or {}
        universe = md.get("universe")
        sl = universe_sl(universe)
        if sl is None:
            continue
        # Already at or better than SL → skip.
        if pnl_pct >= sl - 0.005:
            continue
        entry = float(t["entry_price"] or 0)
        if entry <= 0:
            continue
        ideal_exit = round(entry * (1 + sl), 4)
        new_pnl = round(float(t["position_usd"]) * sl, 2)
        to_fix.append({
            "id": t["id"],
            "mq": (t.get("market_question") or "")[:45],
            "universe": universe,
            "sl_pct": sl,
            "entry": entry,
            "original_exit": float(t.get("exit_price") or 0),
            "original_pnl": float(t.get("pnl_usd") or 0),
            "original_reason": t.get("close_reason"),
            "new_exit": ideal_exit,
            "new_pnl": new_pnl,
        })

    if not to_fix:
        print("Nothing to retrofit.")
        return

    print("=== RETROFIT PREVIEW ===")
    delta_total = 0.0
    for r in to_fix:
        delta = r["new_pnl"] - r["original_pnl"]
        delta_total += delta
        print(f"\n  {r['id'][:8]} | {r['mq']:<46} | {r['universe']} (sl={r['sl_pct']:+.0%})")
        print(f"    entry=${r['entry']:.3f}  exit ${r['original_exit']:.3f} → ${r['new_exit']:.3f}")
        print(f"    PnL  ${r['original_pnl']:+.2f} ({r['original_reason']}) "
              f"→ ${r['new_pnl']:+.2f} (STOP_LOSS_RETROFIT)")
        print(f"    Δ {delta:+.2f}")

    print(f"\n  TOTAL PnL recovered: ${delta_total:+.2f}")

    if not args.apply:
        print("\n  (dry-run — pass --apply to commit)")
        return

    print("\n=== APPLYING ===")
    for r in to_fix:
        try:
            client.table("copy_trades").update({
                "exit_price": r["new_exit"],
                "pnl_usd": r["new_pnl"],
                "pnl_pct": r["sl_pct"],
                "close_reason": "STOP_LOSS_RETROFIT",
            }).eq("id", r["id"]).execute()
            print(f"  ✓ updated {r['id'][:8]}")
        except Exception as e:
            print(f"  ✗ {r['id'][:8]} failed: {e}")
            sys.exit(2)

    # Reconcile portfolio
    p = (
        client.table("portfolio_state_ct")
        .select("current_capital,peak_capital,initial_capital")
        .eq("run_id", run_id)
        .eq("strategy", "SPECIALIST")
        .eq("is_shadow", False)
        .limit(1)
        .execute()
        .data
    )
    if p:
        cur = float(p[0]["current_capital"] or 0)
        peak = float(p[0]["peak_capital"] or 0)
        initial = float(p[0]["initial_capital"] or 0)
        # Recompute current_capital from initial + sum of realized
        all_closed = (
            client.table("copy_trades")
            .select("pnl_usd")
            .eq("run_id", run_id).eq("strategy", "SPECIALIST")
            .eq("is_shadow", False).eq("status", "CLOSED")
            .execute().data
        ) or []
        realized = sum(float(x.get("pnl_usd") or 0) for x in all_closed)
        new_cur = round(initial + realized, 2)
        new_peak = max(peak, new_cur)
        client.table("portfolio_state_ct").update({
            "current_capital": new_cur,
            "peak_capital": new_peak,
        }).eq("run_id", run_id).eq("strategy", "SPECIALIST").eq("is_shadow", False).execute()
        print(f"\n  Portfolio: current_capital ${cur:.2f} → ${new_cur:.2f}")


if __name__ == "__main__":
    main()
