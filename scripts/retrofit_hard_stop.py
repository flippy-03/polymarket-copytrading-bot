"""Retroactively apply the missing hard stop rule to SCALPER real trades.

The copy_monitor never enforced TS_HARD_STOP (-0.20). As a result, trades
whose price crossed -20% without the trailing stop being active first were
held until MARKET_RESOLVED — often at 100% loss. To leave cleaner data
for the weekly backtest, we retrofit any closed real trade that met two
conditions:

  1. Its recorded pnl_pct is worse than HARD_STOP (-0.20).
  2. At some moment between opened_at and closed_at we have a
     market_price_snapshot where price <= entry_price * 0.80.

For qualifying trades we set:
  exit_price   = entry_price * 0.80              (ideal SL execution)
  pnl_pct      = -0.20 (exactly)
  pnl_usd      = position_usd * -0.20
  closed_at    = timestamp of the first snapshot that crossed the threshold
  close_reason = "STOP_LOSS_RETROFIT"   (distinguishes from original SL hits)

Shadows are left untouched — they already had the right SL logic. Only
real SCALPER trades in the current v3.0 run are considered.

The script runs in DRY-RUN mode by default; pass --apply to commit.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"
HARD_STOP_PCT = -0.20


def load_candidates(client):
    return (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,outcome_token_id,entry_price,"
                "exit_price,position_usd,shares,pnl_usd,pnl_pct,"
                "opened_at,closed_at,close_reason")
        .eq("run_id", RUN_SCALPER)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .execute()
        .data
    ) or []


def first_threshold_crossing(client, token_id: str, entry: float,
                              opened_at: str, closed_at: str):
    """Return (snapshot_at, price) of the first snapshot where
    price <= entry * 0.80 within the window, or None."""
    threshold = round(entry * 0.80, 6)
    snaps = (
        client.table("market_price_snapshots")
        .select("snapshot_at,price")
        .eq("outcome_token_id", token_id)
        .gte("snapshot_at", opened_at)
        .lte("snapshot_at", closed_at)
        .order("snapshot_at")
        .limit(5000)
        .execute()
        .data
    ) or []
    for s in snaps:
        if float(s["price"]) <= threshold:
            return s["snapshot_at"], float(s["price"])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Commit the updates. Omit for dry-run.")
    args = parser.parse_args()

    client = _db.get_client()
    trades = load_candidates(client)
    print(f"Scanning {len(trades)} real closed SCALPER trades in run v3.0…")

    to_fix = []
    unchanged = []
    for t in trades:
        pnl_pct = float(t.get("pnl_pct") or 0)
        if pnl_pct >= HARD_STOP_PCT:
            unchanged.append(t)
            continue
        entry = float(t["entry_price"] or 0)
        if entry <= 0:
            unchanged.append(t)
            continue

        crossing = first_threshold_crossing(
            client, t["outcome_token_id"], entry,
            t["opened_at"], t["closed_at"],
        )
        if not crossing:
            unchanged.append(t)
            continue

        cross_ts, cross_price = crossing
        ideal_exit = round(entry * 0.80, 4)
        new_pnl_pct = HARD_STOP_PCT
        new_pnl_usd = round(float(t["position_usd"]) * HARD_STOP_PCT, 2)

        to_fix.append({
            "id": t["id"],
            "market": (t.get("market_question") or "")[:45],
            "wallet": t["source_wallet"][:10] if t.get("source_wallet") else "—",
            "entry": entry,
            "original_exit": float(t.get("exit_price") or 0),
            "original_pnl": float(t.get("pnl_usd") or 0),
            "original_reason": t.get("close_reason"),
            "crossing_ts": cross_ts,
            "crossing_price": cross_price,
            "new_exit": ideal_exit,
            "new_pnl_usd": new_pnl_usd,
            "new_pnl_pct": new_pnl_pct,
        })

    print(f"\n  Trades to retrofit: {len(to_fix)}")
    print(f"  Trades unchanged:   {len(unchanged)}")

    if not to_fix:
        print("\n  No retrofit needed.")
        return

    print("\n=== RETROFIT PREVIEW ===")
    delta_total = 0.0
    for r in to_fix:
        delta = r["new_pnl_usd"] - r["original_pnl"]
        delta_total += delta
        print(f"\n  {r['id'][:8]} | {r['market']:<45} | wallet={r['wallet']}..")
        print(f"    entry=${r['entry']:.3f}  original_exit=${r['original_exit']:.3f}  "
              f"→ new_exit=${r['new_exit']:.3f}")
        print(f"    original PnL=${r['original_pnl']:+.2f} ({r['original_reason']}) "
              f"→ new PnL=${r['new_pnl_usd']:+.2f} (STOP_LOSS_RETROFIT)")
        print(f"    crossing @ {r['crossing_ts'][:16]}  price={r['crossing_price']:.3f}")
        print(f"    Δ PnL: {delta:+.2f}")

    print(f"\n  TOTAL PnL recovered: ${delta_total:+.2f}")

    if not args.apply:
        print("\n  (dry-run — pass --apply to commit)")
        return

    print("\n=== APPLYING UPDATES ===")
    for r in to_fix:
        try:
            client.table("copy_trades").update({
                "exit_price": r["new_exit"],
                "pnl_usd": r["new_pnl_usd"],
                "pnl_pct": r["new_pnl_pct"],
                "closed_at": r["crossing_ts"],
                "close_reason": "STOP_LOSS_RETROFIT",
            }).eq("id", r["id"]).execute()
            print(f"  ✓ updated {r['id'][:8]}")
        except Exception as e:
            print(f"  ✗ failed {r['id'][:8]}: {e}")
            sys.exit(2)

    print(f"\n  Done. {len(to_fix)} trades updated.")


if __name__ == "__main__":
    main()
