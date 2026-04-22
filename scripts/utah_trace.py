"""Investigate the Utah vs Golden Knights loss on 2026-04-22.

Opened 04:21 NO @ $0.57, closed 08:?? at $0.16 = -71.9% STOP_LOSS.
Hard-stop threshold was -50% → exit should have been $0.285. Why did
it cross by 12.5 percentage points? Was the Gamma fallback working?

Checks:
  1. Was the trade opened AFTER the Gamma fallback deploy?
  2. How many samples do we have in the open window?
  3. Max gap between samples?
  4. Price trajectory near the SL threshold.
  5. Does the monitor log show 'price via Gamma fallback' during the
     trade window? (Requires journalctl scrape.)
"""
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


def main() -> None:
    client = _db.get_client()
    rows = (
        client.table("copy_trades")
        .select("id,outcome_token_id,market_polymarket_id,direction,"
                "entry_price,exit_price,pnl_pct,close_reason,"
                "opened_at,closed_at,market_question")
        .eq("strategy", "SPECIALIST")
        .ilike("market_question", "%Utah vs. Golden Knights%")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .order("opened_at", desc=True)
        .limit(3)
        .execute()
        .data
    ) or []

    for t in rows:
        print(f"\n{'=' * 72}")
        print(f"  Trade {t['id'][:8]}  {t['direction']}  entry=${t['entry_price']:.3f}  "
              f"exit=${t['exit_price']:.3f}  pnl={float(t['pnl_pct'])*100:+.1f}%  "
              f"{t['close_reason']}")
        print(f"  opened={t['opened_at']}  closed={t['closed_at']}")

        entry = float(t["entry_price"])
        sl_threshold = round(entry * 0.50, 4)
        print(f"  SL threshold (-50%): price <= {sl_threshold}")

        # Page through all snapshots
        snaps: list[dict] = []
        offset = 0
        while True:
            batch = (
                client.table("market_price_snapshots")
                .select("price,snapshot_at,source")
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

        print(f"  Samples: {len(snaps)}")
        if not snaps:
            continue

        def _parse(s: str) -> datetime:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

        ts_list = [_parse(s["snapshot_at"]) for s in snaps]
        max_gap = 0
        max_gap_at = (None, None, None)
        for i in range(1, len(ts_list)):
            g = (ts_list[i] - ts_list[i-1]).total_seconds()
            if g > max_gap:
                max_gap = g
                max_gap_at = (ts_list[i-1], ts_list[i],
                              float(snaps[i-1]["price"]), float(snaps[i]["price"]))

        print(f"  Max gap: {max_gap/60:.1f} min")
        if max_gap_at[0]:
            a, b, pa, pb = max_gap_at
            print(f"    {a.strftime('%H:%M:%S')} (${pa:.3f}) → "
                  f"{b.strftime('%H:%M:%S')} (${pb:.3f})")

        # First cross of -50%
        first_50 = None
        for s in snaps:
            if float(s["price"]) <= sl_threshold:
                first_50 = s
                break
        if first_50:
            print(f"  First cross ≤ SL: {first_50['snapshot_at'][:19]} "
                  f"price=${float(first_50['price']):.3f}  "
                  f"source={first_50.get('source', '?')}")
        else:
            print(f"  First cross ≤ SL: NEVER observed in snapshots")

        # Sources distribution (clob vs gamma fallback)
        from collections import Counter
        sources = Counter(s.get("source", "?") for s in snaps)
        print(f"  Source distribution: {dict(sources)}")

        # Samples around the SL cross window
        print(f"  Last 8 samples:")
        for s in snaps[-8:]:
            print(f"    {s['snapshot_at'][:19]}  price=${float(s['price']):.4f}  "
                  f"source={s.get('source', '?')}")


if __name__ == "__main__":
    main()
