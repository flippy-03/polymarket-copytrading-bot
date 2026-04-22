"""Estimate the cost (rows, MB) of market_price_snapshots growth, and
the marginal cost of adding _record_price() to the SPECIALIST
position_manager._check_trade path.

Method:
  - Query rows in rolling 1-hour windows for the last 24 hours.
  - Sample one row to estimate average bytes per row.
  - Count DISTINCT outcome_token_id per hour (= rough tick footprint).
  - Project additional rows the proposed change would produce.

The proposed change adds one row per (open real SPECIALIST trade, tick).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


def main() -> None:
    client = _db.get_client()
    now = datetime.now(tz=timezone.utc)

    # Sample row to estimate bytes
    sample = (
        client.table("market_price_snapshots")
        .select("*")
        .limit(1)
        .execute()
        .data
    )
    if sample:
        # Rough estimate: sum of string representations of all values
        row = sample[0]
        approx = sum(len(str(v)) for v in row.values()) + 2 * len(row)
        # Postgres overhead per row ~24 bytes; indexes add ~20% of row size
        row_cost = approx + 24
        print(f"Sample row:\n  {row}")
        print(f"Approx bytes per row (inc. overhead): {row_cost}")

    # Sample several 5-minute windows to estimate rate without timing out
    print(f"\nSnapshots per 5-minute window (sampled at 0h/6h/12h/18h/23h ago):")
    probe_hours = [0.1, 6, 12, 18, 23]
    rates: list[float] = []
    for h in probe_hours:
        t_from = (now - timedelta(hours=h)).isoformat()
        t_to = (now - timedelta(hours=h) + timedelta(minutes=5)).isoformat()
        try:
            r = (
                client.table("market_price_snapshots")
                .select("id")
                .gte("snapshot_at", t_from)
                .lt("snapshot_at", t_to)
                .limit(10000)
                .execute()
                .data
            )
            n = len(r)
            per_hour = n * 12
            rates.append(per_hour)
            label = (now - timedelta(hours=h)).strftime("%m-%d %H:%M")
            print(f"  {label} + 5min: {n:,} rows  → ~{per_hour:,}/hour")
        except Exception as e:
            print(f"  {h}h ago — failed: {e}")

    if rates:
        avg_per_hour = sum(rates) / len(rates)
        per_day = avg_per_hour * 24
        print(f"\n  Estimated rate: ~{avg_per_hour:,.0f} rows/hour = ~{per_day:,.0f} rows/day")
        if sample:
            mb_day = per_day * row_cost / 1024 / 1024
            print(f"  Approx MB/day: {mb_day:.1f} MB  →  30-day: {mb_day * 30:.1f} MB")

    # Count OPEN real SPECIALIST positions right now
    open_spec = (
        client.table("copy_trades")
        .select("id")
        .eq("strategy", "SPECIALIST")
        .eq("status", "OPEN")
        .eq("is_shadow", False)
        .execute()
        .data
    ) or []
    print(f"\nCurrent OPEN real SPECIALIST trades: {len(open_spec)}")
    print("Proposed change: record_price on each tick for these trades.")
    tick_per_minute = 1        # SPECIALIST tick ~30-60s → ~1 per minute
    extra_per_hour = len(open_spec) * tick_per_minute * 60
    print(f"Marginal snapshots from adding _record_price to SPECIALIST monitor:")
    print(f"  assuming tick ~1/min and avg {len(open_spec)} open positions:")
    print(f"  +{extra_per_hour:,} rows/hour → +{extra_per_hour * 24:,} rows/day")
    if sample:
        extra_mb_day = extra_per_hour * 24 * row_cost / 1024 / 1024
        print(f"  +{extra_mb_day:.2f} MB/day = +{extra_mb_day * 30:.1f} MB/month")

    # Supabase Free plan: 500 MB DB + 5 GB egress/mo
    print(f"\nSupabase Free plan limits:")
    print(f"  Database:  500 MB")
    print(f"  Egress:    5 GB / month")


if __name__ == "__main__":
    main()
