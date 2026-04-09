"""
One-shot snapshot cleanup — run directly on the VPS.
Deletes market_snapshots older than 5 days in batches of 500.
Safe to interrupt and re-run — idempotent.

Usage:
    python scripts/cleanup_snapshots_now.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone, timedelta
from src.db import supabase_client as db
from src.utils.logger import logger

BATCH_SIZE = 500
KEEP_DAYS = 5

def main():
    client = db.get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    logger.info(f"Deleting market_snapshots older than {cutoff[:10]} in batches of {BATCH_SIZE}...")

    total_deleted = 0
    batch_num = 0

    for _ in range(20000):  # safety cap ~10M rows
        rows = (
            client.table("market_snapshots")
            .select("id")
            .lt("snapshot_at", cutoff)
            .limit(BATCH_SIZE)
            .execute()
            .data
        )
        if not rows:
            break

        ids = [r["id"] for r in rows]
        client.table("market_snapshots").delete().in_("id", ids).execute()
        total_deleted += len(ids)
        batch_num += 1

        if batch_num % 50 == 0:
            logger.info(f"  ... {total_deleted:,} rows deleted so far")

        if len(ids) < BATCH_SIZE:
            break

    logger.info(f"Done — {total_deleted:,} rows deleted. Last {KEEP_DAYS} days kept.")

if __name__ == "__main__":
    main()
