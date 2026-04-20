"""Gap audit specifically for tokens we held as OPEN trades in last 24h.

The previous aggregate audit hit supabase's default 1000-row limit. Here
we look token-by-token for every distinct outcome_token_id we've opened
a SCALPER trade on, and measure the gap distribution.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


def main() -> None:
    client = _db.get_client()
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=30)).isoformat()

    # Distinct tokens we've had open in last 30h (both real + shadow)
    trades = (
        client.table("copy_trades")
        .select("outcome_token_id,opened_at,closed_at,market_question,is_shadow,close_reason,status")
        .eq("strategy", "SCALPER")
        .gte("opened_at", cutoff)
        .execute()
        .data
    )
    tokens = {t["outcome_token_id"] for t in trades if t.get("outcome_token_id")}
    print(f"Distinct tokens SCALPER has opened in 30h: {len(tokens)}")

    # Fetch snapshots per token
    results = []
    for tok in tokens:
        snaps = (
            client.table("market_price_snapshots")
            .select("price,snapshot_at")
            .eq("outcome_token_id", tok)
            .gte("snapshot_at", cutoff)
            .order("snapshot_at")
            .limit(5000)
            .execute()
            .data
        )
        if not snaps:
            continue

        # associated trades for this token
        token_trades = [t for t in trades if t["outcome_token_id"] == tok]
        # earliest open & latest close for this token
        opens = sorted(t["opened_at"] for t in token_trades)
        closes = sorted([t.get("closed_at") for t in token_trades if t.get("closed_at")])
        first_open = opens[0] if opens else None
        last_close = closes[-1] if closes else None
        sample_mq = (token_trades[0].get("market_question") or "")[:40]

        def _parse(s: str) -> datetime:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        tslist = [_parse(r["snapshot_at"]) for r in snaps]
        gaps = [(tslist[i] - tslist[i-1]).total_seconds() for i in range(1, len(tslist))]
        if not gaps:
            continue
        max_gap = max(gaps)
        # Only care about gaps DURING the OPEN window
        window_gaps: list[tuple[datetime, datetime, float]] = []
        if first_open:
            open_dt = datetime.fromisoformat(first_open.replace("Z", "+00:00"))
            if open_dt.tzinfo is None:
                open_dt = open_dt.replace(tzinfo=timezone.utc)
            if last_close:
                close_dt = datetime.fromisoformat(last_close.replace("Z", "+00:00"))
                if close_dt.tzinfo is None:
                    close_dt = close_dt.replace(tzinfo=timezone.utc)
            else:
                close_dt = datetime.now(tz=timezone.utc)
            for i in range(1, len(tslist)):
                a, b = tslist[i-1], tslist[i]
                if open_dt <= b and a <= close_dt:
                    gap_s = (b - a).total_seconds()
                    if gap_s > 120:    # >2x our nominal 30s interval
                        window_gaps.append((a, b, gap_s))

        results.append({
            "market": sample_mq,
            "token": tok[:12],
            "samples": len(snaps),
            "first_snap": tslist[0].strftime("%m-%d %H:%M"),
            "last_snap": tslist[-1].strftime("%m-%d %H:%M"),
            "max_gap_s": max_gap,
            "window_gaps": window_gaps,
            "first_open": first_open[:16] if first_open else None,
            "last_close": last_close[:16] if last_close else None,
            "reasons": [t.get("close_reason") for t in token_trades if t.get("close_reason")],
        })

    # Sort by biggest gap first
    results.sort(key=lambda r: -r["max_gap_s"])

    print(f"\n{'Market':<40} {'Samples':>8} {'MaxGap':>8} {'FirstSnap':>12} {'LastSnap':>12}  Reasons")
    for r in results:
        print(f"  {r['market']:<38} {r['samples']:>8} "
              f"{r['max_gap_s']/60:>6.1f}m {r['first_snap']:>14} {r['last_snap']:>14}  "
              f"{r['reasons']}")
        if r["window_gaps"]:
            for a, b, gap_s in r["window_gaps"][:3]:
                print(f"      gap: {a.strftime('%m-%d %H:%M:%S')} → "
                      f"{b.strftime('%m-%d %H:%M:%S')}  ({gap_s/60:.1f} min)")


if __name__ == "__main__":
    main()
