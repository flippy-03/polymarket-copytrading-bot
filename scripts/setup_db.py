"""
setup_db.py — Verify Supabase connection and print the migration SQL.

The SQL schema must be applied manually via the Supabase SQL Editor
(RLS restrictions prevent running DDL from service role in some tiers).

Usage:
    python scripts/setup_db.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db import supabase_client as db
from src.utils.logger import logger


MIGRATION_FILE = os.path.join(
    os.path.dirname(__file__), "..", "src", "db", "migrations", "001_initial_schema.sql"
)


def main():
    logger.info("=== Polymarket Contrarian — DB Setup ===")

    # 1. Verify connection
    logger.info("Testing Supabase connection...")
    ok = db.verify_connection()
    if not ok:
        logger.error("Cannot connect to Supabase. Check .env credentials.")
        sys.exit(1)

    # 2. Check if tables already exist
    try:
        markets = db.select("markets")
        logger.info(f"'markets' table exists — {len(markets)} rows")
        wallets = db.select("watched_wallets")
        logger.info(f"'watched_wallets' table exists — {len(wallets)} rows")
        portfolio = db.select("portfolio_state")
        logger.info(f"'portfolio_state' table exists — {len(portfolio)} rows")
        logger.info("Schema already applied. Ready to run.")
    except Exception as e:
        logger.warning(f"Tables not found ({e})")
        logger.info("")
        logger.info("=" * 60)
        logger.info("ACTION REQUIRED: Apply the schema manually in Supabase SQL Editor")
        logger.info("File: src/db/migrations/001_initial_schema.sql")
        logger.info("=" * 60)
        logger.info("")

        # Print the SQL for convenience
        with open(MIGRATION_FILE) as f:
            print(f.read())

        sys.exit(0)


if __name__ == "__main__":
    main()
