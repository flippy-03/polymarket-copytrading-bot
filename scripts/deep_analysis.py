"""
Deep Analysis Script — Comprehensive edge analysis across ALL runs.

Fetches all data from Supabase including:
- All paper trades (runs 1, 2, and null)
- All shadow trades (run 0 capacity-blocked)
- All signals (executed + expired)
- Market snapshots for TS trades (to check if they eventually reverted)
- Market details for classification

Generates:
  scripts/deep_analysis_data.json — complete enriched dataset

Usage:
  python scripts/deep_analysis.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

OUTPUT_DIR = Path(__file__).parent


def sb_get(table: str, params: dict) -> list:
    """Fetch from Supabase REST API with retry."""
    params.setdefault("limit", 1000)
    for attempt in range(3):
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/{table}",
                headers=HEADERS,
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [!] Attempt {attempt+1} failed for {table}: {e}")
            if attempt < 2:
                import time
                time.sleep(5)
    print(f"  [!!] Failed to fetch {table} after 3 attempts")
    return []


def classify_market(question: str) -> str:
    q = (question or "").lower()
    if any(x in q for x in ["bitcoin", "btc"]):
        if any(x in q for x in ["reach", "dip to", "march 30", "april"]):
            if "on " in q and any(d in q for d in ["march 25", "march 26", "march 27"]):
                return "CRYPTO_BTC_DAILY"
            return "CRYPTO_BTC_WEEKLY"
        return "CRYPTO_BTC_DAILY"
    if any(x in q for x in ["ethereum", "eth"]):
        if any(x in q for x in ["reach", "dip to", "march 30", "april"]):
            if "on " in q and any(d in q for d in ["march 25", "march 26", "march 27"]):
                return "CRYPTO_ETH_DAILY"
            return "CRYPTO_ETH_WEEKLY"
        return "CRYPTO_ETH_DAILY"
    if any(x in q for x in ["solana", "dogecoin"]): return "CRYPTO_OTHER"
    if any(x in q for x in ["elon", "musk", "tweet", "post "]) and "tweet" in q or "post" in q: return "SOCIAL_COUNT"
    if any(x in q for x in ["trump"]): return "POLITICS_TRUMP"
    if any(x in q for x in ["tariff"]): return "MACRO_TARIFFS"
    if any(x in q for x in ["fed ", "rate cut", "fomc"]): return "MACRO_FED"
    if any(x in q for x in ["war", "ukraine", "ceasefire"]): return "GEOPOLITICS"
    if any(x in q for x in ["prime minister", "president", "election", "governor"]): return "POLITICS_OTHER"
    if any(x in q for x in ["spread:", "win the", "nba", "nfl", "nhl", "mlb"]): return "SPORTS"
    if any(x in q for x in ["release", "album", "movie", "box office", "kanye"]): return "ENTERTAINMENT"
    return "OTHER_EVENT"


def win_rate(trades):
    if not trades: return 0.0
    return sum(1 for t in trades if (t.get("pnl_usd") or 0) > 0) / len(trades)


def total_pnl(trades):
    return sum(t.get("pnl_usd") or 0 for t in trades)


def avg(lst):
    return sum(lst) / len(lst) if lst else 0.0


# ─────────────────────────────────────────────────────────
# FETCH ALL DATA
# ─────────────────────────────────────────────────────────
print("=" * 60)
print("DEEP ANALYSIS — Fetching all data from Supabase")
print("=" * 60)

print("\n1. Fetching runs...")
runs = sb_get("runs", {"select": "*", "order": "id.asc"})
print(f"   Runs: {len(runs)}")
for r in runs:
    print(f"   Run {r['id']}: {r.get('note', '')}")

print("\n2. Fetching paper trades (run 1)...")
trades_r1 = sb_get("paper_trades", {
    "select": "id,signal_id,market_id,direction,entry_price,exit_price,shares,position_usd,pnl_usd,pnl_pct,opened_at,closed_at,close_reason,status,run_id",
    "run_id": "eq.1", "order": "opened_at.asc",
})
print(f"   Run 1: {len(trades_r1)} trades")

print("   Fetching paper trades (run 2)...")
trades_r2 = sb_get("paper_trades", {
    "select": "id,signal_id,market_id,direction,entry_price,exit_price,shares,position_usd,pnl_usd,pnl_pct,opened_at,closed_at,close_reason,status,run_id",
    "run_id": "eq.2", "order": "opened_at.asc",
})
print(f"   Run 2: {len(trades_r2)} trades")

print("   Fetching paper trades (run null)...")
trades_r0 = sb_get("paper_trades", {
    "select": "id,signal_id,market_id,direction,entry_price,exit_price,shares,position_usd,pnl_usd,pnl_pct,opened_at,closed_at,close_reason,status,run_id",
    "run_id": "is.null", "order": "opened_at.asc",
})
print(f"   Run null: {len(trades_r0)} trades")

all_trades = trades_r1 + trades_r2 + trades_r0

print("\n3. Fetching shadow trades...")
shadows = sb_get("shadow_trades", {"select": "*"})
print(f"   Shadow trades: {len(shadows)}")

print("\n4. Fetching signals...")
signals = sb_get("signals", {
    "select": "id,market_id,status,total_score,divergence_score,momentum_score,smart_wallet_score,direction,confidence,price_at_signal,created_at",
    "limit": 2000,
})
print(f"   Signals: {len(signals)}")

# Collect all market IDs we need
all_market_ids = set()
for t in all_trades:
    if t.get("market_id"): all_market_ids.add(t["market_id"])
for s in signals:
    if s.get("market_id"): all_market_ids.add(s["market_id"])
for sh in shadows:
    if sh.get("market_id"): all_market_ids.add(sh["market_id"])

print(f"\n5. Fetching markets ({len(all_market_ids)} unique IDs)...")
markets = {}
# Fetch in batches of 50
market_list = list(all_market_ids)
for i in range(0, len(market_list), 50):
    batch = market_list[i:i+50]
    ids_str = ",".join(batch)
    result = sb_get("markets", {"select": "id,question,category,yes_price,end_date,resolution", "id": f"in.({ids_str})"})
    for m in result:
        markets[m["id"]] = m
    print(f"   Batch {i//50 + 1}: {len(result)} markets")

print(f"   Total markets fetched: {len(markets)}")

# Build signal map
sig_map = {s["id"]: s for s in signals}

# ─────────────────────────────────────────────────────────
# ENRICH ALL DATA
# ─────────────────────────────────────────────────────────
print("\n6. Enriching trades and shadows...")

def enrich_trade(t):
    sig = sig_map.get(t.get("signal_id"), {})
    mkt = markets.get(t.get("market_id"), {})
    t["_score"] = sig.get("total_score")
    t["_div"] = sig.get("divergence_score")
    t["_mom"] = sig.get("momentum_score")
    t["_sw"] = sig.get("smart_wallet_score")
    t["_conf"] = sig.get("confidence")
    t["_question"] = mkt.get("question", "")
    t["_type"] = classify_market(mkt.get("question", ""))
    t["_resolution"] = mkt.get("resolution")
    t["_yes_price"] = mkt.get("yes_price")
    return t

for t in all_trades:
    enrich_trade(t)

for sh in shadows:
    sig = sig_map.get(sh.get("signal_id"), {})
    mkt = markets.get(sh.get("market_id"), {})
    sh["_score"] = sig.get("total_score")
    sh["_div"] = sig.get("divergence_score")
    sh["_mom"] = sig.get("momentum_score")
    sh["_conf"] = sig.get("confidence")
    sh["_direction"] = sh.get("direction") or sig.get("direction")
    sh["_question"] = mkt.get("question", "")
    sh["_type"] = classify_market(mkt.get("question", ""))
    sh["_resolution"] = mkt.get("resolution")
    sh["_yes_price"] = mkt.get("yes_price")
    sh["_entry"] = sh.get("entry_price") or sig.get("price_at_signal")

# ─────────────────────────────────────────────────────────
# SHADOW TRADE OUTCOME ESTIMATION
# ─────────────────────────────────────────────────────────
print("\n7. Estimating shadow trade outcomes...")
shadow_outcomes = []
for sh in shadows:
    entry = sh.get("_entry")
    direction = sh.get("_direction")
    yes_price = sh.get("_yes_price")
    resolution = sh.get("_resolution")
    if not entry or not direction or yes_price is None:
        continue

    # Use resolution if available, else current price
    if resolution == "YES":
        final_yes = 1.0
    elif resolution == "NO":
        final_yes = 0.0
    else:
        final_yes = yes_price

    if direction == "YES":
        exit_price = final_yes
    else:
        exit_price = 1 - final_yes

    pnl_pct = (exit_price - entry) / entry if entry > 0 else 0

    # Would TP have triggered?
    tp_triggered = pnl_pct >= 0.50
    # Would TS have triggered? (simplified)
    ts_triggered = pnl_pct <= -0.25

    shadow_outcomes.append({
        "signal_id": sh.get("signal_id"),
        "direction": direction,
        "entry": entry,
        "exit": round(exit_price, 4),
        "pnl_pct": round(pnl_pct, 4),
        "outcome": "WIN" if pnl_pct > 0 else "LOSS",
        "tp_would_trigger": tp_triggered,
        "ts_would_trigger": ts_triggered,
        "type": sh.get("_type"),
        "score": sh.get("_score"),
        "question": (sh.get("_question") or "")[:100],
        "blocked_reason": sh.get("blocked_reason"),
        "resolved": resolution in ("YES", "NO"),
    })

if shadow_outcomes:
    resolved = [o for o in shadow_outcomes if o["resolved"]]
    shadow_wins = [o for o in resolved if o["outcome"] == "WIN"]
    print(f"   Shadow outcomes estimated: {len(shadow_outcomes)} total, {len(resolved)} resolved")
    if resolved:
        print(f"   Shadow WR (resolved): {len(shadow_wins)/len(resolved):.1%}")

# ─────────────────────────────────────────────────────────
# SNAPSHOT ANALYSIS FOR TS TRADES
# ─────────────────────────────────────────────────────────
print("\n8. Fetching snapshots for trailing-stop trades...")
ts_trades = [t for t in all_trades if t.get("close_reason") == "TRAILING_STOP" and t.get("status") == "CLOSED"]
ts_reversal_data = []

for t in ts_trades[:20]:  # Limit to avoid timeout
    mid = t.get("market_id")
    closed_at = t.get("closed_at")
    if not mid or not closed_at:
        continue

    # Get snapshots AFTER the trade was closed
    snapshots = sb_get("market_snapshots", {
        "select": "yes_price,snapshot_at",
        "market_id": f"eq.{mid}",
        "snapshot_at": f"gt.{closed_at}",
        "order": "snapshot_at.asc",
        "limit": 200,
    })

    if not snapshots:
        continue

    entry = t.get("entry_price", 0)
    direction = t.get("direction")

    # Check if price eventually reached TP level after we were stopped out
    tp_level = entry * 1.50 if direction == "YES" else entry * 0.50  # Simplified

    max_favorable = 0
    min_adverse = 0
    eventually_won = False

    for snap in snapshots:
        sp = snap.get("yes_price", 0.5)
        if direction == "YES":
            move = (sp - entry) / entry if entry > 0 else 0
        else:
            effective_entry = 1 - entry if entry < 1 else entry
            move = ((1 - sp) - effective_entry) / effective_entry if effective_entry > 0 else 0

        max_favorable = max(max_favorable, move)
        min_adverse = min(min_adverse, move)

        # Did it ever reach +50% from our entry?
        if move >= 0.50:
            eventually_won = True

    # Check resolution
    mkt = markets.get(mid, {})
    resolution = mkt.get("resolution")
    if resolution:
        if direction == "YES" and resolution == "YES":
            eventually_won = True
        elif direction == "NO" and resolution == "NO":
            eventually_won = True

    ts_reversal_data.append({
        "trade_id": t.get("id"),
        "direction": direction,
        "entry": entry,
        "exit": t.get("exit_price"),
        "pnl": t.get("pnl_usd"),
        "score": t.get("_score"),
        "type": t.get("_type"),
        "question": (t.get("_question") or "")[:80],
        "snapshots_after": len(snapshots),
        "max_favorable_after": round(max_favorable, 4),
        "min_adverse_after": round(min_adverse, 4),
        "eventually_won": eventually_won,
        "resolution": resolution,
    })

if ts_reversal_data:
    reverted = [d for d in ts_reversal_data if d["eventually_won"]]
    print(f"   TS trades analyzed: {len(ts_reversal_data)}")
    print(f"   Would have eventually won: {len(reverted)}/{len(ts_reversal_data)} ({len(reverted)/len(ts_reversal_data):.0%})")

# ─────────────────────────────────────────────────────────
# COMPILE OUTPUT
# ─────────────────────────────────────────────────────────
print("\n9. Compiling results...")

closed_all = [t for t in all_trades if t.get("status") == "CLOSED"]

output = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "runs": runs,
    "trade_counts": {
        "run_1": {"total": len(trades_r1), "closed": len([t for t in trades_r1 if t["status"]=="CLOSED"])},
        "run_2": {"total": len(trades_r2), "closed": len([t for t in trades_r2 if t["status"]=="CLOSED"])},
        "run_null": {"total": len(trades_r0), "closed": len([t for t in trades_r0 if t["status"]=="CLOSED"])},
    },
    "all_closed_trades": [{
        "id": t["id"], "run_id": t.get("run_id"), "direction": t["direction"],
        "entry": t.get("entry_price"), "exit": t.get("exit_price"),
        "pnl": t.get("pnl_usd"), "pnl_pct": t.get("pnl_pct"),
        "close_reason": t.get("close_reason"), "score": t.get("_score"),
        "div": t.get("_div"), "mom": t.get("_mom"), "conf": t.get("_conf"),
        "question": t.get("_question", "")[:100], "type": t.get("_type"),
        "opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"),
    } for t in closed_all],
    "shadow_outcomes": shadow_outcomes,
    "ts_reversal_analysis": ts_reversal_data,
    "signal_stats": {
        "total": len(signals),
        "by_status": {status: len([s for s in signals if s["status"]==status]) for status in set(s["status"] for s in signals)},
    },
}

# Save
data_path = OUTPUT_DIR / "deep_analysis_data.json"
with open(data_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nData saved to: {data_path}")
print(f"Total closed trades: {len(closed_all)}")
print(f"Shadow outcomes: {len(shadow_outcomes)}")
print(f"TS reversal data: {len(ts_reversal_data)}")
print("\nDone!")
