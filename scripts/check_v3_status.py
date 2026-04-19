"""One-shot diagnostic for the v3.0 SCALPER run.

Reports:
  1. Any trade row whose id starts with 'a58df12a' (the trailing-stop we
     saw in logs — we want to know which run it belongs to and whether
     it's shadow or real).
  2. SCALPER trade counts grouped by run/status/shadow since 2026-04-18.
  3. Last trade timestamp in Polymarket data-api for each active titular
     of run b4a40e7d, to see if the titulars themselves are operating.

Run on the VPS:
    cd /root/polymarket-copytrading-bot && .venv/bin/python -m scripts.check_v3_status
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db

RUN_ID = "b4a40e7d-50ec-476f-9765-e4fbab02608e"


def main() -> None:
    client = _db.get_client()

    print("=== OPEN trades across all runs (any strategy) ===")
    open_trades = (
        client.table("copy_trades")
        .select("id,run_id,strategy,status,is_shadow,source_wallet,market_question,opened_at")
        .eq("status", "OPEN")
        .order("opened_at", desc=True)
        .limit(30)
        .execute()
        .data
    )
    if not open_trades:
        print("  (no open trades at all)")
    for r in open_trades:
        mq = (r.get("market_question") or "")[:50]
        print(
            f"  id={r['id'][:8]} run={r['run_id'][:8]} {r['strategy']} "
            f"shadow={r['is_shadow']} opened={r['opened_at'][:16]} "
            f"wallet={r['source_wallet'][:10] if r.get('source_wallet') else '—'}.. "
            f"mkt={mq}"
        )

    print("\n=== SCALPER trades per run since 2026-04-18 ===")
    rows = (
        client.table("copy_trades")
        .select("run_id,status,is_shadow")
        .eq("strategy", "SCALPER")
        .gte("opened_at", "2026-04-18")
        .execute()
        .data
    )
    counts = Counter((x["run_id"][:8], x["status"], x["is_shadow"]) for x in rows)
    if not counts:
        print("  (no SCALPER trades since 2026-04-18)")
    for key, n in sorted(counts.items()):
        print(f"  run={key[0]} status={key[1]} shadow={key[2]}: {n}")

    print("\n=== Titular activity on Polymarket data-api ===")
    pool = (
        client.table("scalper_pool")
        .select("wallet_address")
        .eq("run_id", RUN_ID)
        .eq("status", "ACTIVE_TITULAR")
        .execute()
        .data
    )
    now = datetime.now(tz=timezone.utc)
    for p in pool:
        w = p["wallet_address"]
        try:
            r = requests.get(
                "https://data-api.polymarket.com/activity",
                params={
                    "user": w,
                    "type": "TRADE",
                    "limit": 5,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
                timeout=5,
            )
            acts = r.json() if r.status_code == 200 else []
        except Exception as e:
            print(f"  {w[:10]}.. ERROR: {e}")
            continue
        if acts:
            ts = datetime.fromtimestamp(acts[0]["timestamp"], tz=timezone.utc)
            age_h = (now - ts).total_seconds() / 3600
            print(
                f"  {w[:10]}.. last={ts.strftime('%Y-%m-%d %H:%M')}UTC "
                f"({age_h:.1f}h ago)  recent_n={len(acts)}"
            )
        else:
            print(f"  {w[:10]}.. no recent activity")


if __name__ == "__main__":
    main()
