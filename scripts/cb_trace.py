"""Trace the full sequence of events for the 4 SCALPER titulars to see
when each was marked broken and whether trades opened afterward.

For each titular, walk through the chronological ordering of its trades
(both opened_at and closed_at events) and simulate the per-trader
consecutive_losses counter + is_broken flag as register_titular_loss
would have mutated them.
"""
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN = "b4a40e7d-50ec-476f-9765-e4fbab02608e"
LOSS_CUTOFF = -0.02
LIMIT_DEFAULT = 2


def main() -> None:
    client = _db.get_client()

    trades = (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,is_shadow,pnl_pct,pnl_usd,"
                "status,opened_at,closed_at,close_reason")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .order("opened_at", desc=False)
        .execute()
        .data
    ) or []

    # Group events chronologically by wallet
    # Each event is either OPEN or CLOSE; for the CB, only CLOSE events
    # trigger register_titular_loss.
    events_by_wallet: dict[str, list] = defaultdict(list)
    for t in trades:
        w = t.get("source_wallet") or "?"
        events_by_wallet[w].append(("OPEN", t["opened_at"], t))
        if t.get("closed_at") and t["status"] == "CLOSED":
            events_by_wallet[w].append(("CLOSE", t["closed_at"], t))

    for w, events in events_by_wallet.items():
        events.sort(key=lambda x: x[1])
        print(f"\n=== {w[:10]}.. ===")
        streak = 0
        broken = False
        for kind, ts, t in events:
            mq = (t.get("market_question") or "")[:35]
            short_ts = ts[:16].replace("T", " ")
            if kind == "OPEN":
                status = "🚫BLOCKED" if broken else "✅ would open"
                print(f"  {short_ts}  OPEN  {mq:<36} {status}")
            else:
                pct = float(t.get("pnl_pct") or 0)
                if pct < LOSS_CUTOFF:
                    streak += 1
                else:
                    streak = 0
                if streak >= LIMIT_DEFAULT:
                    broken = True
                print(f"  {short_ts}  CLOSE {mq:<36} pnl={pct:+.2%} "
                      f"streak={streak} broken={broken} ({t.get('close_reason')})")


if __name__ == "__main__":
    main()
