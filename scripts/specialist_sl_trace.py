"""Diagnose the 3 big SPECIALIST sports losses:
  - Senators vs Hurricanes YES (MARKET_RESOLVED -100%)
  - Timberwolves vs Nuggets NO (STOP_LOSS -79%)
  - Spread: Cavaliers -8.5 NO (STOP_LOSS -67%)

Goal: compare snapshot price trajectory against the configured SL
threshold (-50% for sports_game_winner) to see whether a tighter stop
(-40%) would have caught the loss earlier, or whether the gap was so
large that no reasonable threshold would have helped.
"""
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


CANDIDATES = [
    "Senators vs. Hurricanes",
    "Timberwolves vs. Nuggets",
    "Spread: Cavaliers",
]


def main() -> None:
    client = _db.get_client()

    for market_like in CANDIDATES:
        print(f"\n{'=' * 78}")
        print(f"  {market_like}")
        print("=" * 78)
        # Get the WORST (most negative pnl) closed trade that matches
        rows = (
            client.table("copy_trades")
            .select("id,outcome_token_id,direction,entry_price,exit_price,"
                    "pnl_pct,close_reason,opened_at,closed_at,market_question")
            .eq("strategy", "SPECIALIST")
            .ilike("market_question", f"%{market_like}%")
            .eq("is_shadow", False)
            .eq("status", "CLOSED")
            .order("pnl_pct", desc=False)
            .limit(1)
            .execute()
            .data
        ) or []
        if not rows:
            print("  (not found)")
            continue
        t = rows[0]
        entry = float(t["entry_price"])
        exit_px = float(t["exit_price"])
        print(f"  {t['direction']}  entry=${entry:.3f}  exit=${exit_px:.3f}  "
              f"pnl={float(t['pnl_pct'])*100:+.1f}%  reason={t['close_reason']}")
        print(f"  opened={t['opened_at'][:16]}  closed={t['closed_at'][:16]}")
        threshold_50 = round(entry * 0.50, 4)
        threshold_40 = round(entry * 0.60, 4)
        print(f"  SL threshold -50%: price <= {threshold_50}")
        print(f"  SL threshold -40%: price <= {threshold_40}")

        # Fetch snapshots chronologically (ASC), paging past the default
        # 1000-row limit to cover long hold windows.
        snaps: list[dict] = []
        offset = 0
        while True:
            batch = (
                client.table("market_price_snapshots")
                .select("price,snapshot_at")
                .eq("outcome_token_id", t["outcome_token_id"])
                .gte("snapshot_at", t["opened_at"])
                .lte("snapshot_at", t["closed_at"])
                .order("snapshot_at")
                .range(offset, offset + 999)
                .execute()
                .data
            ) or []
            if not batch:
                break
            snaps.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000
        print(f"  Samples during open window: {len(snaps)}")

        # Find first cross of -40% and -50%
        first_40 = None
        first_50 = None
        for s in snaps:
            p = float(s["price"])
            if first_40 is None and p <= threshold_40:
                first_40 = (s["snapshot_at"], p)
            if first_50 is None and p <= threshold_50:
                first_50 = (s["snapshot_at"], p)
                break

        if first_40:
            ts, p = first_40
            print(f"  First cross ≤ -40% ($≤{threshold_40}): {ts[:19]}  price=${p:.3f}")
        else:
            print(f"  First cross ≤ -40%: NEVER observed in our samples")

        if first_50:
            ts, p = first_50
            print(f"  First cross ≤ -50% ($≤{threshold_50}): {ts[:19]}  price=${p:.3f}")
        else:
            print(f"  First cross ≤ -50%: NEVER observed in our samples")

        # Max gap between consecutive samples while the trade was open
        if len(snaps) >= 2:
            def _parse(s: str) -> datetime:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            ts_list = [_parse(s["snapshot_at"]) for s in snaps]
            max_gap = 0
            max_gap_at = (None, None)
            for i in range(1, len(ts_list)):
                g = (ts_list[i] - ts_list[i-1]).total_seconds()
                if g > max_gap:
                    max_gap = g
                    max_gap_at = (ts_list[i-1], ts_list[i])
            print(f"  Max gap between samples: {max_gap/60:.1f} min "
                  f"({max_gap_at[0].strftime('%H:%M:%S') if max_gap_at[0] else '?'} "
                  f"→ {max_gap_at[1].strftime('%H:%M:%S') if max_gap_at[1] else '?'})")

        # Last few samples near close
        print(f"  Last 5 samples before close:")
        for s in snaps[-5:]:
            print(f"    {s['snapshot_at'][:19]}  price=${float(s['price']):.4f}")


if __name__ == "__main__":
    main()
