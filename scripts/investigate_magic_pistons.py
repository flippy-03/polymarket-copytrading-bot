"""Deep-dive on the Magic vs Pistons market that lost 100%.

Goals:
  1. Identify the exact conditionId and eventSlug.
  2. Fetch full trade history from Polymarket data-api to see price trajectory.
  3. Fetch market metadata from Gamma — what was the question, when did it
     resolve, what outcome won.
  4. Show timeline: bot opens → game starts → price moves → resolution.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db

RUN = "b4a40e7d-50ec-476f-9765-e4fbab02608e"


def main() -> None:
    client = _db.get_client()

    # 1. Find the two losing trades
    rows = (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,direction,outcome_token_id,"
                "entry_price,exit_price,position_usd,pnl_usd,close_reason,status,"
                "is_shadow,opened_at,closed_at,market_polymarket_id,metadata")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .ilike("market_question", "%Magic vs. Pistons%")
        .execute()
        .data
    )
    print(f"Found {len(rows)} Magic vs Pistons trades")
    if not rows:
        return

    conditionId = rows[0]["market_polymarket_id"]
    token_id = rows[0]["outcome_token_id"]
    print(f"\n  conditionId: {conditionId}")
    print(f"  token_id:    {token_id}")
    print(f"  direction:   {rows[0]['direction']}  (we bet this)")

    for r in rows:
        meta = r.get("metadata") or {}
        opened = (r.get("opened_at") or "?")[:16]
        closed = (r.get("closed_at") or "—")[:16]
        shadow = r.get("is_shadow", "?")
        print(f"\n  Trade {r['id'][:8]} wallet={r['source_wallet'][:10]}.. shadow={shadow}")
        print(f"    status={r.get('status')} opened={opened} closed={closed}")
        print(f"    entry=${r.get('entry_price')} exit=${r.get('exit_price')} size=${r.get('position_usd')}")
        print(f"    pnl=${r.get('pnl_usd')} reason={r.get('close_reason')}")
        print(f"    titular_price={meta.get('titular_price')} titular_usdc={meta.get('titular_usdc')}")
        print(f"    closes_at={meta.get('closes_at')}")

    # 2. Fetch Gamma market metadata
    print("\n=== GAMMA MARKET METADATA ===")
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"condition_ids": conditionId},
            timeout=10,
        )
        data = r.json() if r.status_code == 200 else []
        if data and isinstance(data, list):
            m = data[0]
            print(f"  question: {m.get('question')}")
            print(f"  slug:     {m.get('slug')}")
            print(f"  endDate:  {m.get('endDate')}")
            print(f"  gameStartTime: {m.get('gameStartTime')}")
            print(f"  closed:   {m.get('closed')}")
            print(f"  active:   {m.get('active')}")
            print(f"  outcomes: {m.get('outcomes')}")
            print(f"  outcomePrices: {m.get('outcomePrices')}")
            events = m.get("events") or []
            if events:
                e = events[0]
                print(f"  event.slug:  {e.get('slug')}")
                print(f"  event.title: {e.get('title')}")
                print(f"  event.endDate: {e.get('endDate')}")
    except Exception as e:
        print(f"  gamma fetch error: {e}")

    # 3. Fetch full trade history (all users) for this market from data-api
    print("\n=== POLYMARKET TRADES ON THIS MARKET (last 500) ===")
    try:
        r = requests.get(
            "https://data-api.polymarket.com/trades",
            params={"market": conditionId, "limit": 500},
            timeout=10,
        )
        trades = r.json() if r.status_code == 200 else []
        if not isinstance(trades, list):
            trades = []
        print(f"  Total samples: {len(trades)}")

        if trades:
            # Only look at trades on our outcome (NO token)
            our_side = [t for t in trades if t.get("asset") == token_id]
            print(f"  Samples on our side (NO token): {len(our_side)}")

            # Timeline of prices sorted ascending
            samples = sorted(
                [(t.get("timestamp"), float(t.get("price") or 0), t.get("side"),
                  float(t.get("size") or 0), float(t.get("usdcSize") or 0))
                 for t in our_side if t.get("timestamp")],
                key=lambda x: x[0],
            )

            print("\n  Price samples around our entries and resolution:")
            # Print every Nth sample + key timestamps
            entry_ts = int(datetime.fromisoformat(rows[0]["opened_at"].replace("Z", "+00:00")).timestamp())
            close_ts = int(datetime.fromisoformat(rows[0]["closed_at"].replace("Z", "+00:00")).timestamp())

            buckets: list[tuple[str, list]] = [
                ("Before entry", [s for s in samples if s[0] < entry_ts - 1800]),
                ("~Around entry", [s for s in samples if entry_ts - 1800 <= s[0] <= entry_ts + 3600]),
                ("Mid-game", [s for s in samples if entry_ts + 3600 < s[0] < close_ts - 3600]),
                ("Near close", [s for s in samples if close_ts - 3600 <= s[0] <= close_ts]),
            ]
            for label, xs in buckets:
                if not xs:
                    continue
                prices = [p for _, p, _, _, _ in xs]
                print(f"\n  {label}: {len(xs)} samples")
                print(f"    price: min={min(prices):.3f} max={max(prices):.3f} "
                      f"first={xs[0][1]:.3f} last={xs[-1][1]:.3f}")
                ts_first = datetime.fromtimestamp(xs[0][0], tz=timezone.utc)
                ts_last = datetime.fromtimestamp(xs[-1][0], tz=timezone.utc)
                print(f"    time: {ts_first.strftime('%H:%M:%S')} → {ts_last.strftime('%H:%M:%S')} UTC")
                # Show last 3 samples in this bucket
                for ts, p, side, sz, usdc in xs[-3:]:
                    t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
                    print(f"      {t} side={side} px={p:.3f} size={sz:.2f} usdc=${usdc:.2f}")
    except Exception as e:
        print(f"  trades fetch error: {e}")

    # 4. Price history from our own price_cache if available
    print("\n=== OUR PRICE_CACHE (si existe) ===")
    try:
        pc = (
            client.table("price_cache")
            .select("token_id,price,recorded_at")
            .eq("token_id", token_id)
            .order("recorded_at", desc=False)
            .limit(100)
            .execute()
            .data
        )
        print(f"  Cached prices: {len(pc)}")
        if pc:
            print(f"    first: {pc[0]['recorded_at'][:19]} @ {pc[0]['price']}")
            print(f"    last:  {pc[-1]['recorded_at'][:19]} @ {pc[-1]['price']}")
            # Show every Nth
            step = max(1, len(pc) // 10)
            for p in pc[::step]:
                print(f"    {p['recorded_at'][:19]} price={p['price']}")
    except Exception as e:
        print(f"  price_cache error: {e}")


if __name__ == "__main__":
    main()
