"""
cleanup_bad_signals.py

1. Expire all ACTIVE signals with entry outside [0.20, 0.80] — generated with
   buggy code before the signal_engine price filter fixes (2026-03-28/29).
2. Close the YES@0.055 position opened with the old code (entry < MIN_CONTRARIAN_PRICE).
   Uses current Gamma API price to compute exit.
3. Rebuilds portfolio_state from all CLOSED trades (run_id=2).

Run once manually:
    PYTHONPATH=. python scripts/cleanup_bad_signals.py
"""

from datetime import datetime, timezone
import httpx
from src.db import supabase_client as db

MIN_CONTRARIAN_PRICE = 0.20
BAD_TRADE_ID = "fac3a949-ce59-409b-a33c-cfd1d225f6c1"  # YES @ 0.055


def expire_bad_signals(client) -> int:
    """Expire ACTIVE signals whose entry is outside [0.20, 0.80]."""
    result = client.table("signals").select("*").eq("status", "ACTIVE").execute()
    signals = result.data or []

    expired = 0
    for s in signals:
        price = s.get("price_at_signal")
        direction = s.get("direction")
        if price is None:
            entry = None
        elif direction == "YES":
            entry = float(price)
        else:
            entry = round(1 - float(price), 4)

        bad = (
            entry is None
            or entry < MIN_CONTRARIAN_PRICE
            or entry > (1 - MIN_CONTRARIAN_PRICE)
        )
        if bad:
            client.table("signals").update({"status": "EXPIRED"}).eq("id", s["id"]).execute()
            print(f"  Expired signal {s['id'][:8]}... | {direction} price={price} entry={entry}")
            expired += 1

    return expired


def get_current_yes_price(polymarket_id: str) -> float | None:
    """Fetch current yes_price from Gamma API by numeric polymarket_id."""
    try:
        r = httpx.get(f"https://gamma-api.polymarket.com/markets/{polymarket_id}", timeout=10)
        r.raise_for_status()
        data = r.json()
        prices = data.get("outcomePrices")
        if prices:
            import json
            p = json.loads(prices) if isinstance(prices, str) else prices
            return float(p[0])
    except Exception as e:
        print(f"  Gamma API error: {e}")
    return None


def close_bad_trade(client) -> bool:
    """Close the YES@0.055 position using current market price."""
    result = client.table("paper_trades").select("*").eq("id", BAD_TRADE_ID).execute()
    if not result.data:
        print(f"Trade {BAD_TRADE_ID[:8]}... not found — skipping")
        return False

    trade = result.data[0]
    if trade["status"] != "OPEN":
        print(f"Trade {BAD_TRADE_ID[:8]}... is already {trade['status']} — skipping")
        return False

    # Get numeric polymarket_id to query Gamma API
    market_id = trade["market_id"]
    mkt = client.table("markets").select("polymarket_id,question").eq("id", market_id).execute()
    if not mkt.data:
        print(f"Market {market_id[:8]}... not found in DB")
        return False

    poly_id = mkt.data[0].get("polymarket_id")
    question = mkt.data[0].get("question", "")[:60]
    print(f"\nTrade: YES @ {trade['entry_price']} | {question}")
    print(f"  polymarket_id: {poly_id}")

    yes_price = get_current_yes_price(str(poly_id)) if poly_id else None

    if yes_price is None:
        # Fallback: use latest snapshot
        snap = (
            client.table("market_snapshots")
            .select("yes_price")
            .eq("market_id", market_id)
            .not_.is_("yes_price", "null")
            .order("snapshot_at", desc=True)
            .limit(1)
            .execute()
        )
        if snap.data:
            yes_price = float(snap.data[0]["yes_price"])
            print(f"  Using snapshot price: yes={yes_price}")
        else:
            print("  No price available — cannot close trade safely")
            return False
    else:
        print(f"  Gamma API yes_price: {yes_price}")

    # For YES trade: exit_price = yes_price
    exit_price = round(yes_price, 4)
    entry_price = float(trade["entry_price"])
    shares = float(trade["shares"])
    position_usd = float(trade["position_usd"])

    pnl_usd = round((exit_price - entry_price) * shares, 2)
    pnl_pct = round(pnl_usd / position_usd, 4) if position_usd > 0 else 0
    now = datetime.now(tz=timezone.utc).isoformat()

    client.table("paper_trades").update({
        "exit_price": exit_price,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "close_reason": "INVALID_SIGNAL",
        "closed_at": now,
        "status": "CLOSED",
    }).eq("id", BAD_TRADE_ID).execute()

    result_str = "WIN" if pnl_usd > 0 else "LOSS"
    print(f"  Closed [{result_str}] entry={entry_price} exit={exit_price} P&L=${pnl_usd:+.2f} ({pnl_pct:+.1%})")
    return True


def rebuild_portfolio_state(client) -> None:
    """Replay all CLOSED trades for run_id=2 to recompute portfolio_state."""
    port = client.table("portfolio_state").select("*").order("run_id", desc=True).limit(1).execute().data[0]
    run_id = port["run_id"]
    initial_capital = float(port["initial_capital"])

    trades = (
        client.table("paper_trades")
        .select("*")
        .eq("status", "CLOSED")
        .eq("run_id", run_id)
        .order("closed_at", desc=False)
        .execute()
        .data
    )

    total_pnl = 0.0
    wins = 0
    losses = 0
    consecutive_losses = 0
    max_streak = 0
    peak_capital = initial_capital
    max_drawdown = 0.0

    for t in trades:
        pnl = float(t.get("pnl_usd") or 0)
        total_pnl += pnl
        current_capital = initial_capital + total_pnl
        if pnl > 0:
            wins += 1
            consecutive_losses = 0
        else:
            losses += 1
            consecutive_losses += 1
            max_streak = max(max_streak, consecutive_losses)

        peak_capital = max(peak_capital, current_capital)
        dd = (peak_capital - current_capital) / peak_capital if peak_capital > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    total_closed = wins + losses
    win_rate = round(wins / total_closed, 4) if total_closed > 0 else 0

    # Open positions: locked capital
    open_trades = (
        client.table("paper_trades")
        .select("position_usd")
        .eq("status", "OPEN")
        .eq("run_id", run_id)
        .execute()
        .data
    )
    locked = sum(float(t["position_usd"]) for t in open_trades)
    open_count = len(open_trades)
    current_capital = round(initial_capital + total_pnl - locked, 2)

    client.table("portfolio_state").update({
        "current_capital": current_capital,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_capital, 4),
        "winning_trades": wins,
        "losing_trades": losses,
        "total_trades": total_closed + open_count,
        "win_rate": win_rate,
        "max_drawdown": round(max_drawdown, 4),
        "consecutive_losses": consecutive_losses,
        "open_positions": open_count,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("id", port["id"]).execute()

    print(f"\n=== Portfolio rebuilt ===")
    print(f"  Capital:  ${initial_capital} -> ${current_capital}")
    print(f"  Total PnL: ${total_pnl:+.2f} ({total_pnl/initial_capital:+.1%})")
    print(f"  Trades:   {total_closed} closed ({wins}W {losses}L) + {open_count} open")
    print(f"  Win rate: {win_rate*100:.0f}%")
    print(f"  Max DD:   {max_drawdown:.1%}")
    print(f"  Streak:   {consecutive_losses} (peak: {max_streak})")


if __name__ == "__main__":
    client = db.get_client()

    print("=== Step 1: Expire bad signals ===")
    n = expire_bad_signals(client)
    print(f"  Expired {n} signal(s)\n")

    print("=== Step 2: Close bad trade (YES@0.055) ===")
    closed = close_bad_trade(client)

    print("\n=== Step 3: Rebuild portfolio state ===")
    rebuild_portfolio_state(client)

    print("\nDone.")
