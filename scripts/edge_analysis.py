"""
Edge Analysis Script — Run against Supabase data to validate signal quality.

Generates:
  scripts/edge_analysis_report.txt — human-readable report
  scripts/edge_analysis_data.json  — raw data for further analysis

Usage:
  python scripts/edge_analysis.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

PRICE_TARGET_KEYWORDS = [
    "reach $", "dip to $", "hit $", "fall to $", "drop to $",
    "above $", "below $", "be between $",
    "price of bitcoin", "price of ethereum", "price of eth", "price of btc",
]

OUTPUT_DIR = Path(__file__).parent


def sb_get(table: str, params: dict) -> list:
    params.setdefault("limit", 1000)
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def is_crypto(question: str) -> bool:
    q = (question or "").lower()
    return any(kw in q for kw in PRICE_TARGET_KEYWORDS)


def avg(lst):
    return sum(lst) / len(lst) if lst else 0.0


def win_rate(trades):
    wins = [t for t in trades if (t.get("pnl_usd") or 0) > 0]
    return len(wins) / len(trades) if trades else 0.0


def pnl_total(trades):
    return sum(t.get("pnl_usd") or 0 for t in trades)


# ─────────────────────────────────────────────────────────
# FETCH DATA
# ─────────────────────────────────────────────────────────

print("Fetching data from Supabase...")

signals_raw = sb_get("signals", {"select": "id,market_id,status,total_score,divergence_score,momentum_score,smart_wallet_score,direction,confidence,price_at_signal,created_at,expires_at", "limit": 500})
trades_raw = sb_get("paper_trades", {"select": "id,signal_id,market_id,direction,entry_price,exit_price,shares,position_usd,pnl_usd,pnl_pct,opened_at,closed_at,close_reason,status", "status": "eq.CLOSED", "limit": 500})
markets_raw = sb_get("markets", {"select": "id,question,category,yes_price,volume_24h,end_date", "limit": 1000})

# Build lookup maps
market_by_id = {m["id"]: m for m in markets_raw}
signal_by_id = {s["id"]: s for s in signals_raw}

print(f"  Signals: {len(signals_raw)} | Trades: {len(trades_raw)} | Markets: {len(markets_raw)}")

# Enrich trades with signal scores and market question
for t in trades_raw:
    sig = signal_by_id.get(t.get("signal_id"), {})
    mkt = market_by_id.get(t.get("market_id"), {})
    t["total_score"] = sig.get("total_score")
    t["divergence_score"] = sig.get("divergence_score")
    t["momentum_score"] = sig.get("momentum_score")
    t["market_question"] = mkt.get("question", "")
    t["is_crypto"] = is_crypto(mkt.get("question", ""))

closed = [t for t in trades_raw if t.get("close_reason")]
wins = [t for t in closed if (t.get("pnl_usd") or 0) > 0]
losses = [t for t in closed if (t.get("pnl_usd") or 0) < 0]

report_lines = []
data = {}

def h(title):
    report_lines.append("")
    report_lines.append("=" * 60)
    report_lines.append(title)
    report_lines.append("=" * 60)

def line(s=""):
    report_lines.append(s)


# ─────────────────────────────────────────────────────────
# A. OVERALL SUMMARY
# ─────────────────────────────────────────────────────────
h("A. OVERALL SUMMARY")
line(f"Total closed trades:  {len(closed)}")
line(f"Wins:                 {len(wins)}")
line(f"Losses:               {len(losses)}")
line(f"Win rate:             {win_rate(closed):.1%}")
line(f"Total P&L:            ${pnl_total(closed):.2f}")
line(f"Avg win:              ${avg([t['pnl_usd'] for t in wins]):.2f}")
line(f"Avg loss:             ${avg([t['pnl_usd'] for t in losses]):.2f}")
if wins and losses:
    rr = abs(avg([t['pnl_usd'] for t in wins]) / avg([t['pnl_usd'] for t in losses]))
    line(f"Win/Loss ratio:       {rr:.2f}x")

data["summary"] = {
    "total": len(closed), "wins": len(wins), "losses": len(losses),
    "win_rate": win_rate(closed), "total_pnl": pnl_total(closed),
}


# ─────────────────────────────────────────────────────────
# B. WIN RATE BY SCORE BUCKET
# ─────────────────────────────────────────────────────────
h("B. WIN RATE BY total_score BUCKET")
buckets = {"65-70": [], "70-75": [], "75-80": [], "80+": []}
for t in closed:
    s = t.get("total_score")
    if s is None:
        continue
    if s < 70:
        buckets["65-70"].append(t)
    elif s < 75:
        buckets["70-75"].append(t)
    elif s < 80:
        buckets["75-80"].append(t)
    else:
        buckets["80+"].append(t)

data["by_score_bucket"] = {}
for bucket, trades in buckets.items():
    wr = win_rate(trades)
    pnl = pnl_total(trades)
    line(f"  [{bucket}]  n={len(trades):3d}  WR={wr:.0%}  P&L=${pnl:.2f}")
    data["by_score_bucket"][bucket] = {"n": len(trades), "win_rate": wr, "pnl": pnl}

line("")
line("  divergence_score correlation:")
div_buckets = {"<50": [], "50-70": [], "70+": []}
for t in closed:
    s = t.get("divergence_score")
    if s is None:
        continue
    if s < 50:
        div_buckets["<50"].append(t)
    elif s < 70:
        div_buckets["50-70"].append(t)
    else:
        div_buckets["70+"].append(t)

data["by_divergence_score"] = {}
for bucket, trades in div_buckets.items():
    wr = win_rate(trades)
    pnl = pnl_total(trades)
    line(f"  div[{bucket}]  n={len(trades):3d}  WR={wr:.0%}  P&L=${pnl:.2f}")
    data["by_divergence_score"][bucket] = {"n": len(trades), "win_rate": wr, "pnl": pnl}

line("")
line("  momentum_score correlation:")
mom_buckets = {"<30": [], "30-60": [], "60+": []}
for t in closed:
    s = t.get("momentum_score")
    if s is None:
        continue
    if s < 30:
        mom_buckets["<30"].append(t)
    elif s < 60:
        mom_buckets["30-60"].append(t)
    else:
        mom_buckets["60+"].append(t)

data["by_momentum_score"] = {}
for bucket, trades in mom_buckets.items():
    wr = win_rate(trades)
    pnl = pnl_total(trades)
    line(f"  mom[{bucket}]  n={len(trades):3d}  WR={wr:.0%}  P&L=${pnl:.2f}")
    data["by_momentum_score"][bucket] = {"n": len(trades), "win_rate": wr, "pnl": pnl}


# ─────────────────────────────────────────────────────────
# C. WIN RATE BY CLOSE REASON
# ─────────────────────────────────────────────────────────
h("C. WIN RATE BY CLOSE REASON")
from collections import defaultdict
by_reason = defaultdict(list)
for t in closed:
    by_reason[t["close_reason"]].append(t)

data["by_close_reason"] = {}
for reason, trades in sorted(by_reason.items()):
    wr = win_rate(trades)
    pnl = pnl_total(trades)
    avg_dur = ""
    durations = []
    for t in trades:
        if t.get("opened_at") and t.get("closed_at"):
            try:
                o = datetime.fromisoformat(t["opened_at"].replace("Z",""))
                c = datetime.fromisoformat(t["closed_at"].replace("Z",""))
                durations.append((c - o).total_seconds() / 3600)
            except Exception:
                pass
    if durations:
        avg_dur = f"  avg_hold={avg(durations):.1f}h"
    line(f"  {reason:20s}  n={len(trades):3d}  WR={wr:.0%}  P&L=${pnl:.2f}{avg_dur}")
    data["by_close_reason"][reason] = {"n": len(trades), "win_rate": wr, "pnl": pnl, "avg_hold_hours": avg(durations) if durations else None}

# Check TRAILING_STOP trades: did any reach +20% before stopping?
ts_trades = by_reason.get("TRAILING_STOP", [])
if ts_trades:
    line("")
    line(f"  TRAILING_STOP detail (all {len(ts_trades)} are losses):")
    for t in ts_trades:
        entry = t.get("entry_price", 0)
        exit_ = t.get("exit_price", 0)
        pnl = t.get("pnl_usd", 0)
        direction = t.get("direction", "")
        question = (t.get("market_question", "") or "")[:60]
        line(f"    {direction:3s}  entry={entry:.3f}  exit={exit_:.3f}  P&L=${pnl:.2f}  {question}")


# ─────────────────────────────────────────────────────────
# D. WIN RATE BY DIRECTION
# ─────────────────────────────────────────────────────────
h("D. WIN RATE BY DIRECTION (YES vs NO)")
yes_trades = [t for t in closed if t.get("direction") == "YES"]
no_trades = [t for t in closed if t.get("direction") == "NO"]
line(f"  YES  n={len(yes_trades):3d}  WR={win_rate(yes_trades):.0%}  P&L=${pnl_total(yes_trades):.2f}  avg=${avg([t['pnl_usd'] for t in yes_trades]):.2f}")
line(f"  NO   n={len(no_trades):3d}  WR={win_rate(no_trades):.0%}  P&L=${pnl_total(no_trades):.2f}  avg=${avg([t['pnl_usd'] for t in no_trades]):.2f}")
data["by_direction"] = {
    "YES": {"n": len(yes_trades), "win_rate": win_rate(yes_trades), "pnl": pnl_total(yes_trades)},
    "NO": {"n": len(no_trades), "win_rate": win_rate(no_trades), "pnl": pnl_total(no_trades)},
}


# ─────────────────────────────────────────────────────────
# E. CRYPTO PRICE-TARGET vs EVENT MARKETS
# ─────────────────────────────────────────────────────────
h("E. CRYPTO PRICE-TARGET vs EVENT MARKETS")
crypto_trades = [t for t in closed if t.get("is_crypto")]
event_trades = [t for t in closed if not t.get("is_crypto")]
line(f"  CRYPTO  n={len(crypto_trades):3d}  WR={win_rate(crypto_trades):.0%}  P&L=${pnl_total(crypto_trades):.2f}")
line(f"  EVENT   n={len(event_trades):3d}  WR={win_rate(event_trades):.0%}  P&L=${pnl_total(event_trades):.2f}")

# Also breakdown crypto by close reason
if crypto_trades:
    line("")
    line("  Crypto breakdown by close reason:")
    crypto_by_reason = defaultdict(list)
    for t in crypto_trades:
        crypto_by_reason[t["close_reason"]].append(t)
    for reason, trades in sorted(crypto_by_reason.items()):
        line(f"    {reason:20s}  n={len(trades):2d}  WR={win_rate(trades):.0%}  P&L=${pnl_total(trades):.2f}")

data["by_market_type"] = {
    "crypto_price_target": {"n": len(crypto_trades), "win_rate": win_rate(crypto_trades), "pnl": pnl_total(crypto_trades)},
    "event": {"n": len(event_trades), "win_rate": win_rate(event_trades), "pnl": pnl_total(event_trades)},
}


# ─────────────────────────────────────────────────────────
# F. EXPIRED SIGNALS — SHADOW ANALYSIS
# ─────────────────────────────────────────────────────────
h("F. EXPIRED SIGNALS — WHAT DID WE MISS?")
expired = [s for s in signals_raw if s["status"] == "EXPIRED"]
executed = [s for s in signals_raw if s["status"] == "EXECUTED"]
line(f"  Total signals: {len(signals_raw)}")
line(f"  Executed: {len(executed)} ({len(executed)/len(signals_raw):.0%})")
line(f"  Expired:  {len(expired)} ({len(expired)/len(signals_raw):.0%})")
line("")
line(f"  Avg score — executed: {avg([s.get('total_score') or 0 for s in executed]):.1f}")
line(f"  Avg score — expired:  {avg([s.get('total_score') or 0 for s in expired]):.1f}")
line("")

# For expired signals, try to fetch the market's current price to estimate outcome
expired_crypto = [s for s in expired if is_crypto(market_by_id.get(s.get("market_id"), {}).get("question", ""))]
expired_event = [s for s in expired if not is_crypto(market_by_id.get(s.get("market_id"), {}).get("question", ""))]
line(f"  Expired by type:")
line(f"    crypto:  {len(expired_crypto)}")
line(f"    event:   {len(expired_event)}")

# Try to estimate how expired signals would have performed using resolution data
resolved_markets = {m["id"]: m for m in markets_raw if m.get("yes_price") is not None}
shadow_outcomes = []
for s in expired:
    mkt = resolved_markets.get(s.get("market_id"))
    if not mkt:
        continue
    entry = s.get("price_at_signal")
    direction = s.get("direction")
    if not entry or not direction:
        continue
    current_yes = mkt.get("yes_price", 0.5)
    current_price = current_yes if direction == "YES" else (1 - current_yes)
    pnl_pct = (current_price - entry) / entry if entry > 0 else 0
    outcome = "WIN" if pnl_pct > 0 else "LOSS"
    shadow_outcomes.append({"signal_id": s["id"], "direction": direction, "entry": entry, "current_price": current_price, "pnl_pct": pnl_pct, "outcome": outcome, "is_crypto": is_crypto(mkt.get("question",""))})

if shadow_outcomes:
    shadow_wins = [o for o in shadow_outcomes if o["outcome"] == "WIN"]
    shadow_crypto = [o for o in shadow_outcomes if o["is_crypto"]]
    shadow_event = [o for o in shadow_outcomes if not o["is_crypto"]]
    line(f"  Shadow outcome (current price vs signal price, {len(shadow_outcomes)} resolved):")
    line(f"    Overall WR:  {len(shadow_wins)/len(shadow_outcomes):.0%} ({len(shadow_wins)}/{len(shadow_outcomes)})")
    if shadow_crypto:
        sw_c = [o for o in shadow_crypto if o["outcome"]=="WIN"]
        line(f"    Crypto WR:   {len(sw_c)/len(shadow_crypto):.0%} ({len(sw_c)}/{len(shadow_crypto)})")
    if shadow_event:
        sw_e = [o for o in shadow_event if o["outcome"]=="WIN"]
        line(f"    Event WR:    {len(sw_e)/len(shadow_event):.0%} ({len(sw_e)}/{len(shadow_event)})")

data["expired_signals"] = {
    "total": len(expired), "crypto": len(expired_crypto), "event": len(expired_event),
    "shadow_outcomes": shadow_outcomes,
}


# ─────────────────────────────────────────────────────────
# G. KEY OBSERVATIONS & RECOMMENDATIONS
# ─────────────────────────────────────────────────────────
h("G. KEY OBSERVATIONS")

ts_wr = win_rate(by_reason.get("TRAILING_STOP", []))
tp_wr = win_rate(by_reason.get("TAKE_PROFIT", []))
res_wr = win_rate(by_reason.get("RESOLUTION", []))

if ts_wr == 0.0 and len(by_reason.get("TRAILING_STOP", [])) > 5:
    line("  [!] TRAILING_STOP = 100% losses. Our 25% trailing stop is too tight:")
    line("      Signals that trigger TS likely have mean-reversion that overshoots.")
    line("      Consider: wider stop (35-40%) or time-based exit instead.")

if tp_wr == 1.0 and len(by_reason.get("TAKE_PROFIT", [])) > 3:
    line("  [+] TAKE_PROFIT = 100% wins. Our 50% target is well-calibrated.")
    line("      These are our best trades — signals where divergence resolved cleanly.")

if win_rate(crypto_trades) < 0.35 and len(crypto_trades) > 3:
    line(f"  [!] Crypto price-target WR = {win_rate(crypto_trades):.0%}. These markets are noise.")
    line("      Recommend: reduce MAX_CRYPTO_POSITIONS to 1 or exclude entirely.")

if win_rate(no_trades) > win_rate(yes_trades) + 0.15:
    line(f"  [+] NO trades outperform YES ({win_rate(no_trades):.0%} vs {win_rate(yes_trades):.0%}).")
    line("      Our contrarian edge is stronger fading overbought markets (NO direction).")

exec_pct = len(executed) / len(signals_raw) if signals_raw else 0
if exec_pct < 0.50:
    line(f"  [i] Only {exec_pct:.0%} of signals get executed (capacity + drift filter).")
    line("      Expired signals may represent missed opportunities.")


# ─────────────────────────────────────────────────────────
# WRITE OUTPUT
# ─────────────────────────────────────────────────────────
report_path = OUTPUT_DIR / "edge_analysis_report.txt"
data_path = OUTPUT_DIR / "edge_analysis_data.json"

report_content = "\n".join(report_lines)
print(report_content)

with open(report_path, "w", encoding="utf-8") as f:
    f.write(f"Edge Analysis — generated {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    f.write(report_content)

with open(data_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, default=str)

print(f"\nReport saved to: {report_path}")
print(f"Data saved to:   {data_path}")
