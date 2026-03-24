"""
Entry point: Signal Engine loop — Phase 2.
Evaluates all candidate markets every 5 minutes and generates contrarian signals.

Run alongside run_collector.py (separate terminal).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import schedule

from src.db import supabase_client as db
from src.signals.signal_engine import run_signal_engine
from src.utils.logger import logger
from src.utils.config import SIGNAL_CHECK_INTERVAL_SECONDS


def job():
    logger.info("--- SIGNAL ENGINE CYCLE ---")
    try:
        count = run_signal_engine()
        if count:
            logger.info(f"Generated {count} new signal(s) this cycle")
    except Exception as e:
        logger.error(f"Signal engine cycle crashed: {e}")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Polymarket Contrarian Bot — Phase 2: Signal Engine")
    logger.info("=" * 60)
    logger.info(f"  Check interval: every {SIGNAL_CHECK_INTERVAL_SECONDS // 60} min")
    logger.info(f"  Signal threshold: score ≥ 65")

    if not db.verify_connection():
        logger.error("Supabase connection failed. Exiting.")
        exit(1)

    # Run once immediately
    job()

    interval_min = SIGNAL_CHECK_INTERVAL_SECONDS // 60
    schedule.every(interval_min).minutes.do(job)
    logger.info(f"Scheduler started — running every {interval_min} min. Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(10)
