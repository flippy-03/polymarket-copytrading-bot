"""
Data cleanup job — runs once daily.

Retention policy for market_snapshots:
  <  48h : keep all (needed for signal engine)
  48h-7d : keep 1 snapshot per hour per market
  7d-30d : keep 1 snapshot per day per market
  > 30d  : delete everything

Usage:
  python scripts/run_cleanup.py            # run once
  python scripts/run_cleanup.py --schedule # run daily at 03:00
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import schedule
import time
from datetime import datetime, timezone, timedelta

from src.db import supabase_client as db
from src.utils.logger import logger


# ── Retention boundaries ──────────────────────────────────────────────────────
KEEP_ALL_HOURS       = 48
HOURLY_BUCKET_DAYS   = 7
DAILY_BUCKET_DAYS    = 30
DELETE_AFTER_DAYS    = 30
DELETE_BATCH_SIZE    = 200


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _bucket_hour(dt: datetime) -> str:
    """Truncate to hour: '2026-03-21T14'"""
    return dt.strftime("%Y-%m-%dT%H")


def _bucket_day(dt: datetime) -> str:
    """Truncate to day: '2026-03-21'"""
    return dt.strftime("%Y-%m-%d")


def _delete_ids(client, ids: list[str]) -> int:
    """Delete snapshot IDs in batches. Returns count deleted."""
    deleted = 0
    for i in range(0, len(ids), DELETE_BATCH_SIZE):
        batch = ids[i : i + DELETE_BATCH_SIZE]
        client.table("market_snapshots").delete().in_("id", batch).execute()
        deleted += len(batch)
    return deleted


def run_cleanup() -> dict:
    """
    Execute the cleanup cycle.
    Returns dict with counts: {kept_all, thinned_hourly, thinned_daily, deleted_old, total_removed}.
    """
    client = db.get_client()
    now = datetime.now(tz=timezone.utc)

    cutoff_keep_all   = now - timedelta(hours=KEEP_ALL_HOURS)
    cutoff_hourly     = now - timedelta(days=HOURLY_BUCKET_DAYS)
    cutoff_daily      = now - timedelta(days=DAILY_BUCKET_DAYS)
    cutoff_delete_all = now - timedelta(days=DELETE_AFTER_DAYS)

    logger.info("=" * 56)
    logger.info("Cleanup job started")
    logger.info(f"  Keep all:      last {KEEP_ALL_HOURS}h (since {cutoff_keep_all.strftime('%Y-%m-%d %H:%M')} UTC)")
    logger.info(f"  Hourly bucket: {KEEP_ALL_HOURS}h - {HOURLY_BUCKET_DAYS}d")
    logger.info(f"  Daily bucket:  {HOURLY_BUCKET_DAYS}d - {DAILY_BUCKET_DAYS}d")
    logger.info(f"  Delete all:    older than {DELETE_AFTER_DAYS}d")
    logger.info("=" * 56)

    # ── Fetch all snapshot metadata (paginated) ───────────────────────────────
    all_rows = []
    offset = 0
    while True:
        batch = (
            client.table("market_snapshots")
            .select("id,market_id,snapshot_at")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        all_rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    logger.info(f"Total snapshots in DB: {len(all_rows)}")

    ids_to_delete: list[str] = []
    kept_all = thinned_hourly = thinned_daily = deleted_old = 0

    # Group rows by age bucket
    zone_keep_all   = []   # < 48h  → untouched
    zone_hourly     = []   # 48h-7d → keep 1/hr/market
    zone_daily      = []   # 7d-30d → keep 1/day/market
    zone_delete_all = []   # > 30d  → delete unconditionally

    for row in all_rows:
        ts = _parse_ts(row["snapshot_at"])
        if ts >= cutoff_keep_all:
            zone_keep_all.append(row)
        elif ts >= cutoff_hourly:
            zone_hourly.append(row)
        elif ts >= cutoff_daily:
            zone_daily.append(row)
        else:
            zone_delete_all.append(row)

    kept_all = len(zone_keep_all)

    # ── Zone: 48h-7d → 1 per hour per market ─────────────────────────────────
    # For each (market_id, hour_bucket), keep the row with the earliest snapshot_at
    hourly_keeper: dict[str, str] = {}   # key -> id to keep
    for row in zone_hourly:
        ts = _parse_ts(row["snapshot_at"])
        key = f"{row['market_id']}|{_bucket_hour(ts)}"
        if key not in hourly_keeper:
            hourly_keeper[key] = (row["id"], ts)
        else:
            if ts < hourly_keeper[key][1]:
                ids_to_delete.append(hourly_keeper[key][0])
                hourly_keeper[key] = (row["id"], ts)
            else:
                ids_to_delete.append(row["id"])

    thinned_hourly = len(zone_hourly) - len(hourly_keeper)

    # ── Zone: 7d-30d → 1 per day per market ──────────────────────────────────
    daily_keeper: dict[str, tuple] = {}
    for row in zone_daily:
        ts = _parse_ts(row["snapshot_at"])
        key = f"{row['market_id']}|{_bucket_day(ts)}"
        if key not in daily_keeper:
            daily_keeper[key] = (row["id"], ts)
        else:
            if ts < daily_keeper[key][1]:
                ids_to_delete.append(daily_keeper[key][0])
                daily_keeper[key] = (row["id"], ts)
            else:
                ids_to_delete.append(row["id"])

    thinned_daily = len(zone_daily) - len(daily_keeper)

    # ── Zone: > 30d → delete all ─────────────────────────────────────────────
    ids_to_delete.extend(row["id"] for row in zone_delete_all)
    deleted_old = len(zone_delete_all)

    # ── Execute deletions ─────────────────────────────────────────────────────
    total_removed = 0
    if ids_to_delete:
        logger.info(f"Deleting {len(ids_to_delete)} snapshots...")
        total_removed = _delete_ids(client, ids_to_delete)
    else:
        logger.info("Nothing to delete — DB is clean")

    remaining = len(all_rows) - total_removed
    logger.info("=" * 56)
    logger.info(f"Cleanup complete:")
    logger.info(f"  Untouched (<48h):        {kept_all}")
    logger.info(f"  Thinned to 1/hr (48h-7d): {len(hourly_keeper)} kept, {thinned_hourly} removed")
    logger.info(f"  Thinned to 1/day (7-30d): {len(daily_keeper)} kept, {thinned_daily} removed")
    logger.info(f"  Deleted (>30d):            {deleted_old}")
    logger.info(f"  Total removed:             {total_removed}")
    logger.info(f"  Snapshots remaining:       {remaining}")
    logger.info("=" * 56)

    return {
        "kept_all": kept_all,
        "thinned_hourly": thinned_hourly,
        "thinned_daily": thinned_daily,
        "deleted_old": deleted_old,
        "total_removed": total_removed,
        "remaining": remaining,
    }


def main():
    parser = argparse.ArgumentParser(description="Snapshot cleanup job")
    parser.add_argument("--schedule", action="store_true", help="Run on schedule (daily at 03:00 UTC)")
    args = parser.parse_args()

    db.verify_connection()

    if args.schedule:
        logger.info("Cleanup scheduler started — will run daily at 03:00 UTC")
        run_cleanup()  # Run immediately on start
        schedule.every().day.at("03:00").do(run_cleanup)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
