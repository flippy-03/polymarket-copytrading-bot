"""
resolve_stuck_positions.py

Closes the 4 resolved-but-stuck OPEN positions in run_id=2 and
recalculates portfolio_state from scratch by replaying all closed trades.

Run once manually:
    python scripts/resolve_stuck_positions.py

Safe to re-run: checks status before touching each trade.
"""

from datetime import datetime, timezone
from src.db import supabase_client as db

# ── Resolved markets (verified via Gamma API 2026-03-28) ──────────────────────
# outcomePrices: [yes_price, no_price] at resolution
# YES=0 → market resolved NO → NO holders get paid 1.0
# YES=1 → market resolved YES → YES holders get paid 1.0

RESOLVED = [
    {
        "trade_id": "e8924b78-86b4-4a61-88cd-b2e2b6c7c612",
        "question": "Will the price of Ethereum be above $2,100 on March 26?",
        "direction": "NO",
        "entry_price": 0.65,
        "shares": 67.31,
        "position_usd": 43.75,
        "exit_yes_price": 0.0,   # resolved NO
    },
    {
        "trade_id": "800e40b6-7356-490f-bd76-1ff649b2ab93",
        "question": "Will the price of Bitcoin be above $70,000 on March 26?",
        "direction": "NO",
        "entry_price": 0.73,
        "shares": 68.53,
        "position_usd": 50.03,
        "exit_yes_price": 0.0,   # resolved NO
    },
    {
        "trade_id": "827de426-90c0-4256-a60e-ef765c7ebe06",
        "question": "Will Kanye release BULLY by March 27?",
        "direction": "NO",
        "entry_price": 0.71,
        "shares": 61.9,
        "position_usd": 43.95,
        "exit_yes_price": 0.0,   # resolved NO
    },
    {
        "trade_id": "cc828c69-56d6-4f5d-8a38-a83eb73249ed",
        "question": "Spread: Avalanche (-1.5)",
        "direction": "YES",
        "entry_price": 0.55,
        "shares": 86.36,
        "position_usd": 47.50,
        "exit_yes_price": 1.0,   # resolved YES
    },
]

# Velasco market: still active, update yes_price so position_manager can track it
VELASCO_MARKET_ID = "9684dfa0-2d30-4ccb-b5da-5e83a96a05a8"
VELASCO_YES_PRICE = 0.369  # from Gamma API 2026-03-28


def _exit_price_for_trade(direction: str, exit_yes: float) -> float:
    """Convert yes-resolution price to the trade's directional price."""
    if direction == "YES":
        return exit_yes
    else:
        return round(1 - exit_yes, 4)


def close_resolved_trades(client) -> list[dict]:
    """
    Close each resolved trade. Returns list of closures with P&L.
    Skips any trade not currently OPEN (safe to re-run).
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    closures = []

    for t in RESOLVED:
        # Check current status
        row = client.table("paper_trades").select("status").eq("id", t["trade_id"]).execute()
        if not row.data or row.data[0]["status"] != "OPEN":
            print(f"  SKIP (already closed): {t['question'][:50]}")
            continue

        exit_price = _exit_price_for_trade(t["direction"], t["exit_yes_price"])
        pnl_usd = round((exit_price - t["entry_price"]) * t["shares"], 2)
        pnl_pct = round(pnl_usd / t["position_usd"], 4) if t["position_usd"] > 0 else 0

        client.table("paper_trades").update({
            "exit_price": exit_price,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "close_reason": "RESOLUTION",
            "closed_at": now,
            "status": "CLOSED",
        }).eq("id", t["trade_id"]).execute()

        result = "WIN" if pnl_usd > 0 else "LOSS"
        print(f"  CLOSED [{result}] {t['direction']} | {t['question'][:50]}")
        print(f"    entry={t['entry_price']:.3f} exit={exit_price:.3f} | P&L ${pnl_usd:+.2f} ({pnl_pct:+.1%})")

        closures.append({**t, "exit_price": exit_price, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct})

    return closures


def rebuild_portfolio_state(client) -> dict:
    """
    Rebuild portfolio_state for run_id=2 by replaying all CLOSED trades
    in chronological order. Single source of truth — ignores current state values.
    """
    trades = (
        client.table("paper_trades")
        .select("pnl_usd,position_usd,direction,status,closed_at,opened_at")
        .eq("run_id", 2)
        .in_("status", ["CLOSED"])
        .order("closed_at", desc=False)
        .execute()
        .data
    )

    initial_capital = 1000.0
    capital = initial_capital
    total_pnl = 0.0
    winning = 0
    losing = 0
    max_dd = 0.0
    consecutive_losses = 0

    for t in trades:
        pnl = float(t["pnl_usd"] or 0)
        pos_usd = float(t["position_usd"] or 0)

        returned = pos_usd + pnl
        capital = round(capital + returned - pos_usd, 2)  # net effect: capital += pnl

        # Actually capital tracking: we deducted pos_usd on open, now return pos_usd+pnl
        # But since we're replaying from scratch on closed trades only, just track net PnL
        total_pnl = round(total_pnl + pnl, 2)

        if pnl > 0:
            winning += 1
            consecutive_losses = 0
        else:
            losing += 1
            consecutive_losses += 1

        current_capital_at_close = initial_capital + total_pnl
        current_dd = round((initial_capital - current_capital_at_close) / initial_capital, 4)
        if current_dd > max_dd:
            max_dd = current_dd

    total_closed = winning + losing
    win_rate = round(winning / total_closed, 4) if total_closed > 0 else 0

    # Count open positions for run_id=2
    open_pos = len(
        client.table("paper_trades")
        .select("id")
        .eq("run_id", 2)
        .eq("status", "OPEN")
        .execute()
        .data
    )

    # Total trades opened in run_id=2 (CLOSED + OPEN, excluding CANCELLED)
    total_trades_opened = len(
        client.table("paper_trades")
        .select("id")
        .eq("run_id", 2)
        .in_("status", ["CLOSED", "OPEN"])
        .execute()
        .data
    )

    # Capital: initial minus what's locked in open positions
    open_trades = (
        client.table("paper_trades")
        .select("position_usd")
        .eq("run_id", 2)
        .eq("status", "OPEN")
        .execute()
        .data
    )
    locked_capital = sum(float(t["position_usd"] or 0) for t in open_trades)
    current_capital = round(initial_capital + total_pnl - locked_capital, 2)

    # CB: if 3+ consecutive losses on last trades, still active? Check CB expiry.
    state_row = (
        client.table("portfolio_state")
        .select("circuit_broken_until")
        .eq("run_id", 2)
        .execute()
        .data
    )
    cb_until = state_row[0]["circuit_broken_until"] if state_row else None
    cb_active = False
    if cb_until:
        until_dt = datetime.fromisoformat(cb_until)
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=timezone.utc)
        cb_active = datetime.now(tz=timezone.utc) < until_dt

    return {
        "current_capital": current_capital,
        "total_pnl": total_pnl,
        "total_pnl_pct": round(total_pnl / initial_capital, 4),
        "total_trades": total_trades_opened,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "open_positions": open_pos,
        "consecutive_losses": consecutive_losses,
        "is_circuit_broken": cb_active,
    }


def main():
    client = db.get_client()

    print("\n=== STEP 1: Close 4 resolved positions ===")
    closures = close_resolved_trades(client)
    total_new_pnl = sum(c["pnl_usd"] for c in closures)
    print(f"\n  Closed {len(closures)} trades | Net P&L: ${total_new_pnl:+.2f}")

    print("\n=== STEP 2: Update Velasco market price ===")
    client.table("markets").update({
        "yes_price": VELASCO_YES_PRICE,
        "no_price": round(1 - VELASCO_YES_PRICE, 4),
    }).eq("id", VELASCO_MARKET_ID).execute()
    print(f"  Velasco yes_price = {VELASCO_YES_PRICE} (market still active)")

    print("\n=== STEP 3: Rebuild portfolio_state from trade history ===")
    new_state = rebuild_portfolio_state(client)

    # Apply to DB
    client.table("portfolio_state").update({
        **new_state,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("run_id", 2).execute()

    print(f"  Capital:          ${new_state['current_capital']:.2f}")
    print(f"  Total P&L:        ${new_state['total_pnl']:+.2f} ({new_state['total_pnl_pct']:+.1%})")
    print(f"  Trades:           {new_state['total_trades']} total | {new_state['winning_trades']}W {new_state['losing_trades']}L")
    print(f"  Win rate:         {new_state['win_rate']:.1%}")
    print(f"  Max drawdown:     {new_state['max_drawdown']:.1%}")
    print(f"  Open positions:   {new_state['open_positions']}")
    print(f"  Loss streak:      {new_state['consecutive_losses']}")
    print(f"  Circuit breaker:  {'ACTIVE' if new_state['is_circuit_broken'] else 'off'}")
    print("\nDone.")


if __name__ == "__main__":
    main()
