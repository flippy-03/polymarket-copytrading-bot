"""Retroactively apply the missing hard stop rule to SCALPER real trades.

The copy_monitor never enforced TS_HARD_STOP. Trades whose price crossed
the threshold without the trailing stop being active first were held
until MARKET_RESOLVED — often at 100% loss. To leave cleaner data for
the weekly backtest, retrofit any closed real trade that met:

  1. pnl_pct is worse than the category-aware hard stop, OR is exactly
     a previous retrofit value that no longer matches the current rule
     (e.g. previously retrofitted to -20% but the trade is sports and
     should now be -40%).
  2. There is a market_price_snapshot between opened_at and closed_at
     where price crossed the threshold.

Category-aware thresholds (mirror src/strategies/scalper/copy_monitor.py):
  sports_winner / sports_spread / sports_total / sports_futures → -40%
  anything else (crypto_above, financial_*, unclassified, None) → -20%

For qualifying trades:
  exit_price   = entry_price * (1 + hard_stop_pct)
  pnl_pct      = hard_stop_pct (exactly)
  pnl_usd      = position_usd * hard_stop_pct
  closed_at    = timestamp of the first snapshot that crossed the threshold
  close_reason = "STOP_LOSS_RETROFIT"

Shadows are untouched (their SL logic was correct).

DRY-RUN by default; pass --apply to commit.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"

_SPORTS_TYPES = frozenset({
    "sports_winner", "sports_spread", "sports_total", "sports_futures",
})
SPORTS_HARD_STOP_PCT = -0.40
DEFAULT_HARD_STOP_PCT = -0.20


def hard_stop_for(market_type: str | None) -> float:
    if market_type in _SPORTS_TYPES:
        return SPORTS_HARD_STOP_PCT
    return DEFAULT_HARD_STOP_PCT


def trade_market_type(t: dict) -> str | None:
    """Prefer metadata.market_type (set by scalper_executor); fall back to
    the column market_category."""
    md = t.get("metadata") or {}
    return md.get("market_type") or t.get("market_category")


def load_candidates(client):
    return (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,outcome_token_id,entry_price,"
                "exit_price,position_usd,shares,pnl_usd,pnl_pct,"
                "opened_at,closed_at,close_reason,market_category,metadata")
        .eq("run_id", RUN_SCALPER)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .execute()
        .data
    ) or []


def first_threshold_crossing(client, token_id: str, entry: float,
                              opened_at: str, closed_at: str | None,
                              hard_stop_pct: float):
    """Return (snapshot_at, price) of the first snapshot where
    price <= entry * (1 + hard_stop_pct) within the window, or None.

    closed_at can be None to search up to the latest snapshot — useful
    when a previous retrofit shortened the closed_at window and we now
    want to apply a stricter threshold that may have been crossed later.
    """
    threshold = round(entry * (1 + hard_stop_pct), 6)
    q = (
        client.table("market_price_snapshots")
        .select("snapshot_at,price")
        .eq("outcome_token_id", token_id)
        .gte("snapshot_at", opened_at)
        .order("snapshot_at")
        .limit(5000)
    )
    if closed_at is not None:
        q = q.lte("snapshot_at", closed_at)
    snaps = q.execute().data or []
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
        entry = float(t["entry_price"] or 0)
        if entry <= 0:
            unchanged.append(t)
            continue

        mtype = trade_market_type(t)
        ideal_pct = hard_stop_for(mtype)
        reason = t.get("close_reason") or ""
        is_prev_retrofit = reason == "STOP_LOSS_RETROFIT"

        # Skip cases:
        # (a) trade closed naturally above the ideal threshold (winners,
        #     small losses, organic SLs that were milder than the rule).
        # (b) trade is already at the right ideal (matches within tolerance).
        # Re-retrofit when a previous retrofit set a threshold that no
        # longer matches today's category-aware rule (e.g. -20% on sports
        # that should now be -40%).
        already_correct = abs(pnl_pct - ideal_pct) < 1e-3
        if already_correct:
            unchanged.append(t)
            continue
        if not is_prev_retrofit and pnl_pct >= ideal_pct - 1e-3:
            unchanged.append(t)
            continue

        # For previous-retrofit trades, drop the upper bound so we can
        # find a crossing past the artificially-shortened closed_at.
        upper = None if is_prev_retrofit else t["closed_at"]
        crossing = first_threshold_crossing(
            client, t["outcome_token_id"], entry,
            t["opened_at"], upper, ideal_pct,
        )
        if not crossing:
            unchanged.append(t)
            continue

        cross_ts, cross_price = crossing
        ideal_exit = round(entry * (1 + ideal_pct), 4)
        new_pnl_usd = round(float(t["position_usd"]) * ideal_pct, 2)

        to_fix.append({
            "id": t["id"],
            "market": (t.get("market_question") or "")[:45],
            "wallet": t["source_wallet"][:10] if t.get("source_wallet") else "—",
            "market_type": mtype or "—",
            "ideal_pct": ideal_pct,
            "entry": entry,
            "original_exit": float(t.get("exit_price") or 0),
            "original_pnl": float(t.get("pnl_usd") or 0),
            "original_reason": t.get("close_reason"),
            "crossing_ts": cross_ts,
            "crossing_price": cross_price,
            "new_exit": ideal_exit,
            "new_pnl_usd": new_pnl_usd,
            "new_pnl_pct": ideal_pct,
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
        print(f"\n  {r['id'][:8]} | {r['market']:<45} | wallet={r['wallet']}.. "
              f"type={r['market_type']} ideal={r['ideal_pct']:+.0%}")
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
