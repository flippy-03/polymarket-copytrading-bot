"""
Quick integration tests to verify API connectivity.
Run: python tests/test_connections.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.utils.logger import logger
from src.db import supabase_client as db
from src.data.polymarketscan_client import PolymarketScanClient
from src.data.polymarket_client import PolymarketClient


def test_supabase():
    logger.info("Testing Supabase...")
    ok = db.verify_connection()
    assert ok, "Supabase connection failed"
    logger.info("Supabase OK")


def test_polymarketscan_markets():
    logger.info("Testing PolymarketScan: markets...")
    with PolymarketScanClient() as pms:
        markets = pms.get_markets(limit=5)
    assert isinstance(markets, list), f"Expected list, got {type(markets)}"
    logger.info(f"PolymarketScan markets OK — got {len(markets)} markets")
    if markets:
        logger.info(f"  Sample: {markets[0]}")


def test_polymarketscan_whale_trades():
    logger.info("Testing PolymarketScan: whale_trades...")
    with PolymarketScanClient() as pms:
        trades = pms.get_whale_trades(limit=5)
    assert isinstance(trades, list), f"Expected list, got {type(trades)}"
    logger.info(f"PolymarketScan whale_trades OK — got {len(trades)} trades")
    if trades:
        logger.info(f"  Sample: {trades[0]}")


def test_polymarketscan_leaderboard():
    logger.info("Testing PolymarketScan: leaderboard...")
    with PolymarketScanClient() as pms:
        leaders = pms.get_leaderboard(limit=5)
    assert isinstance(leaders, list), f"Expected list, got {type(leaders)}"
    logger.info(f"PolymarketScan leaderboard OK — got {len(leaders)} entries")
    if leaders:
        logger.info(f"  Sample: {leaders[0]}")


def test_polymarket_gamma():
    logger.info("Testing Polymarket Gamma API...")
    with PolymarketClient() as pm:
        markets = pm.get_active_markets(min_volume=10_000, limit=5)
    logger.info(f"Gamma API OK — got {len(markets)} markets")
    if markets:
        logger.info(f"  Sample: {markets[0].get('question', '')[:80]}")


if __name__ == "__main__":
    tests = [
        test_supabase,
        test_polymarketscan_markets,
        test_polymarketscan_whale_trades,
        test_polymarketscan_leaderboard,
        test_polymarket_gamma,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            logger.error(f"FAILED {t.__name__}: {e}")
            failed += 1

    logger.info(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
