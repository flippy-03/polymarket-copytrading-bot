"""
run_collector.py — Phase 1 main loop.

Schedule:
  - Every 2 min  → collect price snapshots for active markets
  - Every 5 min  → fetch whale trades, detect herding, update snapshots
  - Every 1 hr   → re-scan markets (refresh candidates list)
  - Every 24 hr  → seed leaderboard wallets

Usage:
    python scripts/run_collector.py
"""

import sys
import os
import signal
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import schedule

from src.data.market_scanner import scan_markets
from src.data.snapshot_collector import collect_snapshots, get_active_markets_from_db
from src.data.whale_trades_collector import collect_whale_trades, detect_herding
from src.data.leaderboard_seeder import seed_leaderboard
from src.db import supabase_client as db
from src.utils.context_updater import update_context
from src.utils.logger import logger
import logging

os.makedirs("logs", exist_ok=True)

# ── State ─────────────────────────────────────────────────────────────────────

_active_markets: list[dict] = []
_whale_summary: dict = {}
_running = True


def _shutdown(sig, frame):
    global _running
    logger.info("Shutdown signal received")
    _running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── Jobs ──────────────────────────────────────────────────────────────────────

def job_scan_markets():
    global _active_markets
    logger.info("--- JOB: scan_markets ---")
    _active_markets = scan_markets()
    logger.info(f"Active candidate markets: {len(_active_markets)}")


def job_collect_snapshots():
    logger.info("--- JOB: collect_snapshots ---")
    markets = get_active_markets_from_db()
    if not markets:
        logger.warning("No markets with token IDs in DB yet — run market scan first")
        return
    n = collect_snapshots(markets, whale_summary=_whale_summary)
    logger.info(f"Snapshots collected: {n}")


def job_whale_trades():
    global _whale_summary
    logger.info("--- JOB: whale_trades ---")
    summary = collect_whale_trades()
    _whale_summary = summary
    herding = detect_herding(summary)
    if herding:
        logger.info(f"Herding detected in {len(herding)} markets: {herding[:5]}")
    else:
        logger.info(f"No herding detected this cycle (whale data for {len(summary)} markets cached)")


def job_seed_leaderboard():
    logger.info("--- JOB: seed_leaderboard ---")
    n = seed_leaderboard(limit=100)
    logger.info(f"Leaderboard seeded: {n} wallets")


def job_cleanup_snapshots():
    """Delete snapshots older than 5 days in batches to avoid timeout."""
    logger.info("--- JOB: cleanup_snapshots ---")
    client = db.get_client()
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    total_deleted = 0
    for _ in range(200):  # safety cap: max 200 batches = 10M rows
        try:
            result = client.table("market_snapshots").delete().lt("snapshot_at", cutoff).limit(10000).execute()
            deleted = len(result.data) if result.data else 0
            total_deleted += deleted
            if deleted == 0:
                break
        except Exception as e:
            logger.warning(f"Cleanup batch failed: {e}")
            break
    logger.info(f"Snapshots cleanup done — {total_deleted} rows deleted (kept last 5 days)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Polymarket Contrarian Bot — Phase 1: Data Collector")
    logger.info("=" * 60)

    # Verify DB connection
    if not db.verify_connection():
        logger.error("Supabase connection failed. Run: python scripts/setup_db.py")
        sys.exit(1)

    # Initial runs (in order)
    logger.info("Running initial jobs...")
    job_seed_leaderboard()
    job_scan_markets()
    job_collect_snapshots()
    job_whale_trades()

    # Schedule recurring jobs
    schedule.every(2).minutes.do(job_collect_snapshots)
    schedule.every(5).minutes.do(job_whale_trades)
    schedule.every(1).hours.do(job_scan_markets)
    schedule.every(24).hours.do(job_seed_leaderboard)
    schedule.every(12).hours.do(update_context)
    schedule.every(24).hours.do(job_cleanup_snapshots)

    logger.info("Scheduler started. Press Ctrl+C to stop.")
    logger.info(f"  Snapshots:    every 2 min")
    logger.info(f"  Whale trades: every 5 min")
    logger.info(f"  Market scan:  every 1 hr")
    logger.info(f"  Leaderboard:  every 24 hr")
    logger.info(f"  CONTEXT.md:   every 12 hr")
    logger.info(f"  DB cleanup:   every 24 hr (keep 5 days)")

    while _running:
        schedule.run_pending()
        time.sleep(10)

    logger.info("Collector stopped cleanly.")


if __name__ == "__main__":
    main()
