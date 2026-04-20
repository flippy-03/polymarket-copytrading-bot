"""Audit of price-snapshot coverage and shadow vs real SL behaviour.

Answers three questions raised during the Magic vs Pistons postmortem:

  1. Why no price samples between 22:02 and 01:00 UTC?
     - Check our internal market_price_snapshots table for the NO token during
       that exact window. The previous "no samples" claim came from
       Polymarket public /trades endpoint (aggregated trade activity,
       NOT our polling) — easily sparse in pre-game lulls.
     - If WE have samples, the data wasn't missing; it was just not
       visible on the public trade feed.

  2. Are there large polling gaps in the last 24h?
     - Scan market_price_snapshots across all tokens we've touched in 24h and
       measure gap distribution. Threshold: >90s = suspicious (our tick
       is 30s).

  3. Why did shadow trigger SL but real didn't?
     - Shadow uses evaluate_shadow_stops() in clob_exec.py which checks
       pnl_pct <= SHADOW_STOP_LOSS_PCT (-15%) unconditionally.
     - Real uses _update_trailing_stops in copy_monitor.py which ONLY
       checks trailing_stop, and trailing only activates at +8% gain.
       No hard stop branch — confirmed by reading the code.
     - If the price never went up +8% first, the real trade had zero
       downside protection. The shadow and real saw the same prices;
       only their decision logic differed.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"
NO_TOKEN_MAGIC = "3804642364664258692008203858103620068982874574913759475615151897503689960166"


def q1_magic_window():
    print("=" * 72)
    print("Q1 — Samples in OUR market_price_snapshots for Magic vs Pistons NO token")
    print("=" * 72)
    client = _db.get_client()
    # Our polling window: from just before first entry (22:00) to resolution (02:51)
    start = "2026-04-19T22:00:00Z"
    end = "2026-04-20T03:00:00Z"
    try:
        rows = (
            client.table("market_price_snapshots")
            .select("outcome_token_id,price,snapshot_at")
            .eq("outcome_token_id", NO_TOKEN_MAGIC)
            .gte("snapshot_at", start)
            .lte("snapshot_at", end)
            .order("snapshot_at")
            .execute()
            .data
        )
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    print(f"  Total samples: {len(rows)}")
    if not rows:
        print("  (NO samples — this would mean our polling never touched this token)")
        return

    first = rows[0]["snapshot_at"][:19]
    last = rows[-1]["snapshot_at"][:19]
    prices = [float(r["price"]) for r in rows]
    print(f"  First sample:  {first} @ {prices[0]:.4f}")
    print(f"  Last sample:   {last} @ {prices[-1]:.4f}")
    print(f"  Price range:   min={min(prices):.4f} max={max(prices):.4f}")

    # Print every Nth sample so we can see the trajectory
    step = max(1, len(rows) // 20)
    print(f"\n  Trajectory (every {step}th sample):")
    for r in rows[::step]:
        t = r["snapshot_at"][:19].replace("T", " ")
        print(f"    {t}  price={float(r['price']):.4f}")
    # Last sample separately
    t = rows[-1]["snapshot_at"][:19].replace("T", " ")
    print(f"    {t}  price={float(rows[-1]['price']):.4f}  <- last")


def q2_gap_audit():
    print("\n" + "=" * 72)
    print("Q2 — Gap audit over last 24h across all tokens we polled")
    print("=" * 72)
    client = _db.get_client()
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        rows = (
            client.table("market_price_snapshots")
            .select("outcome_token_id,snapshot_at")
            .gte("snapshot_at", cutoff)
            .order("outcome_token_id")
            .order("snapshot_at")
            .limit(20000)
            .execute()
            .data
        )
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    print(f"  Total snapshots in last 24h: {len(rows)}")

    by_token = defaultdict(list)
    for r in rows:
        ts = datetime.fromisoformat(r["snapshot_at"].replace("Z", "+00:00"))
        by_token[r["outcome_token_id"]].append(ts)

    print(f"  Distinct tokens polled: {len(by_token)}")

    # Compute gaps per token, threshold categories
    buckets = {"<60s": 0, "60-90s": 0, "90-300s": 0, "5-15min": 0, "15-60min": 0, ">1h": 0}
    sample_gaps: list[tuple[str, datetime, datetime, float]] = []

    for token, tslist in by_token.items():
        if len(tslist) < 2:
            continue
        for i in range(1, len(tslist)):
            gap_s = (tslist[i] - tslist[i-1]).total_seconds()
            if gap_s < 60:
                buckets["<60s"] += 1
            elif gap_s < 90:
                buckets["60-90s"] += 1
            elif gap_s < 300:
                buckets["90-300s"] += 1
            elif gap_s < 900:
                buckets["5-15min"] += 1
            elif gap_s < 3600:
                buckets["15-60min"] += 1
            else:
                buckets[">1h"] += 1
                sample_gaps.append((token, tslist[i-1], tslist[i], gap_s))

    print(f"\n  Gap distribution between consecutive samples per token:")
    for k, v in buckets.items():
        print(f"    {k:>10}: {v}")

    if sample_gaps:
        print(f"\n  Gaps > 1 hour (top 10):")
        for token, a, b, gap_s in sorted(sample_gaps, key=lambda x: -x[3])[:10]:
            print(f"    {token[:10]}.. | {a.strftime('%m-%d %H:%M')} → "
                  f"{b.strftime('%m-%d %H:%M')}  gap={gap_s/3600:.1f}h")


def q3_shadow_vs_real_sl():
    print("\n" + "=" * 72)
    print("Q3 — Shadow vs Real SL logic comparison (from code)")
    print("=" * 72)
    print("""
  SHADOW trades (evaluate_shadow_stops in clob_exec.py):
    for each open shadow trade:
      price = get_token_price(token)   # CLOB API
      pnl_pct = (price - entry) / entry
      if pnl_pct <= SHADOW_STOP_LOSS_PCT (-0.15):
          close('STOP_LOSS')

  REAL SCALPER trades (_update_trailing_stops in copy_monitor.py):
    for each open real trade:
      price = get_token_price(token)   # same CLOB API
      pct_change = (price - entry) / entry
      high_water = max(prev_hwm, price)
      if not trailing_active and pct_change >= TRAILING_ACTIVATION (+0.08):
          trailing_active = True
      if trailing_active:
          trail_stop = high_water * (1 - TRAILING_TRAIL_PCT)
          if price <= trail_stop:
              close('TRAILING_STOP')
      # --- NO hard-stop branch here ---

  Consequence for Magic vs Pistons:
    - Shadow entry 0.78 → stop_pct -15% triggers at price <= 0.663
    - Real entry 0.78 → trailing never activates (price only went DOWN)
      → no stop check at all → held until market resolved to 0.00

  Config values:
    TS_ACTIVATION = 0.08   (+8%)
    TS_TRAIL_PCT  = 0.15
    TS_HARD_STOP  = -0.20  ← DEFINED but NEVER READ in copy_monitor
    SHADOW_STOP_LOSS_PCT = -0.15
""")


if __name__ == "__main__":
    q1_magic_window()
    q2_gap_audit()
    q3_shadow_vs_real_sl()
