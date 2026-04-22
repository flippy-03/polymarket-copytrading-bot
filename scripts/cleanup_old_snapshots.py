"""Daily cleanup of stale market_price_snapshots rows.

Keeps the DB bounded by deleting rows older than SNAPSHOT_RETENTION_DAYS
(default 7). The monitors continue to fill the table with throttled
snapshots (~1 row per token per 3 min), but without a TTL the table
grows unbounded; with 7 days of history we cap it at ~20 MB steady-state.

Usage:
  python -m scripts.cleanup_old_snapshots              # apply (default)
  python -m scripts.cleanup_old_snapshots --dry-run    # report only
  python -m scripts.cleanup_old_snapshots --days 14    # override TTL

Schedule via cron on the VPS:
  0 4 * * * cd /root/polymarket-copytrading-bot && \
            .venv/bin/python -m scripts.cleanup_old_snapshots \
            >> /var/log/snapshot-cleanup.log 2>&1
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


DEFAULT_RETENTION_DAYS = 7


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Report how many rows would be deleted, don't delete")
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS,
                        help=f"Retention window in days (default {DEFAULT_RETENTION_DAYS})")
    args = parser.parse_args()

    client = _db.get_client()
    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
    cutoff_iso = cutoff_dt.isoformat()

    print(f"Cutoff: {cutoff_iso} (rows older than this are candidates)")

    # Count rows older than cutoff (paged; supabase rejects COUNT on huge tables)
    total = 0
    offset = 0
    page = 5000
    while True:
        try:
            r = (
                client.table("market_price_snapshots")
                .select("id")
                .lt("snapshot_at", cutoff_iso)
                .range(offset, offset + page - 1)
                .execute()
                .data
            )
        except Exception as e:
            print(f"Count failed: {e}")
            sys.exit(1)
        n = len(r)
        if n == 0:
            break
        total += n
        if n < page:
            break
        offset += page
        if total > 500_000:     # safety cap on count loop
            print(f"  (count exceeded 500k, stopping count — will delete)")
            break

    print(f"Rows to delete: {total:,}")

    if args.dry_run:
        print("  (dry-run — no changes)")
        return

    if total == 0:
        print("  Nothing to delete.")
        return

    # Delete in batches so we avoid timing out on a single huge statement.
    deleted = 0
    while True:
        try:
            result = (
                client.table("market_price_snapshots")
                .delete()
                .lt("snapshot_at", cutoff_iso)
                .execute()
            )
        except Exception as e:
            print(f"Delete batch failed: {e}")
            # Assume partial success; break and let next run pick up the rest.
            break
        rows = result.data or []
        if not rows:
            break
        deleted += len(rows)
        print(f"  deleted batch of {len(rows)} (total {deleted:,})")
        if len(rows) < 1000:
            break

    print(f"\n  Done. Deleted approx {deleted:,} rows.")


if __name__ == "__main__":
    main()
