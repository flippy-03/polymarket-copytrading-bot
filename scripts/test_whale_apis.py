"""
Quick sanity test for whale data sources:
  1. PMS Agent API (action=whales)
  2. Falcon Market Insights (agent_id=575) — currently broken server-side
  3. Falcon Whale Trades (agent_id=556) — currently broken server-side

Usage:
  python scripts/test_whale_apis.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx
import json

from src.utils.config import POLYMARKETSCAN_AGENT_API_URL, FALCON_API_URL, FALCON_BEARER_TOKEN
from src.utils.logger import logger


def test_pms_agent_api():
    print("\n=== PMS Agent API (action=whales) ===")
    try:
        r = httpx.get(
            POLYMARKETSCAN_AGENT_API_URL,
            params={"action": "whales", "limit": 5, "agent_id": "contrarian-bot"},
            timeout=15,
        )
        print(f"Status: {r.status_code}")
        body = r.json()
        ok = body.get("ok")
        data = body.get("data", [])
        print(f"ok={ok} | trades returned: {len(data)}")
        if data:
            t = data[0]
            print(f"Sample trade: market_id={t.get('market_id','')[:20]}... "
                  f"side={t.get('side')} amount=${t.get('amount_usd',0):,.0f} "
                  f"title={t.get('market_title','')[:40]}")
        print("PASS" if ok and data else "WARN: empty or error")
    except Exception as e:
        print(f"FAIL: {e}")


def test_falcon_herding():
    print("\n=== Falcon Market Insights (agent_id=575) ===")
    if not FALCON_BEARER_TOKEN:
        print("SKIP: FALCON_BEARER_TOKEN not set in .env")
        return
    try:
        r = httpx.post(
            FALCON_API_URL,
            json={"agent_id": 575, "parameters": {"min_top1_wallet_pct": 30, "min_volume_24h": 10000}},
            headers={"Authorization": f"Bearer {FALCON_BEARER_TOKEN}"},
            timeout=15,
        )
        print(f"Status: {r.status_code}")
        body = r.json()
        if body.get("status") == "error":
            print(f"Server error: {body['error']['message'][:150]}")
            print("FAIL (server-side pipeline issue — known, tracked for future fix)")
        else:
            data = body.get("data", [])
            print(f"Data: {json.dumps(data, indent=2)[:500]}")
            print("PASS")
    except Exception as e:
        print(f"FAIL: {e}")


def test_falcon_whale_trades():
    print("\n=== Falcon Whale Trades (agent_id=556) ===")
    if not FALCON_BEARER_TOKEN:
        print("SKIP: FALCON_BEARER_TOKEN not set in .env")
        return
    try:
        r = httpx.post(
            FALCON_API_URL,
            json={"agent_id": 556, "parameters": {"lookback_seconds": 3600, "wallet_proxy": "ALL"}},
            headers={"Authorization": f"Bearer {FALCON_BEARER_TOKEN}"},
            timeout=15,
        )
        print(f"Status: {r.status_code}")
        body = r.json()
        if body.get("status") == "error":
            print(f"Server error: {body['error']['message'][:150]}")
            print("FAIL (server-side pipeline issue — known, tracked for future fix)")
        else:
            data = body.get("data", [])
            print(f"Data: {json.dumps(data, indent=2)[:500]}")
            print("PASS")
    except Exception as e:
        print(f"FAIL: {e}")


if __name__ == "__main__":
    test_pms_agent_api()
    test_falcon_herding()
    test_falcon_whale_trades()
    print("\nDone.")
