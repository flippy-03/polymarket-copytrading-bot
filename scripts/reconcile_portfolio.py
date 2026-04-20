"""Reconcile SCALPER portfolio_state_ct after the hard-stop retrofit.

The previous trade close flow called apply_trade_to_portfolio with the
original (wrong) pnl_usd. Retroactively editing copy_trades rows does
NOT update the portfolio row. This script computes the delta and applies
it to current_capital / peak_capital consistently.

Strategy:
  - For each real closed SCALPER trade in v3.0 whose close_reason is
    now STOP_LOSS_RETROFIT, look up the previous pnl_usd from a
    sentinel record... actually simpler: we know the retrofit set
    pnl_usd = position_usd * -0.20. We compare to what was there before.

Since we already ran retrofit_hard_stop and have no audit table, the
only clean path is: recompute current_capital from initial_capital +
sum(real closed trade pnl_usd) + sum(real open unrealized pnl, which
we skip — only realized matters for current_capital per
apply_trade_to_portfolio semantics).
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"


def main() -> None:
    client = _db.get_client()

    # Fetch portfolio row (real, not shadow)
    pr = (
        client.table("portfolio_state_ct")
        .select("*")
        .eq("run_id", RUN_SCALPER)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .limit(1)
        .execute()
        .data
    )
    if not pr:
        print("No portfolio row found")
        return
    p = pr[0]
    initial = float(p.get("initial_capital") or 0)
    current_now = float(p.get("current_capital") or 0)
    peak_now = float(p.get("peak_capital") or initial)
    print(f"Portfolio state BEFORE:")
    print(f"  initial_capital: ${initial:.2f}")
    print(f"  current_capital: ${current_now:.2f}")
    print(f"  peak_capital:    ${peak_now:.2f}")

    # Sum realized PnL from closed real trades
    closed = (
        client.table("copy_trades")
        .select("pnl_usd,close_reason")
        .eq("run_id", RUN_SCALPER)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .execute()
        .data
    ) or []
    realized = sum(float(t.get("pnl_usd") or 0) for t in closed)
    expected_current = round(initial + realized, 2)
    print(f"\nRecomputed from closed trades:")
    print(f"  realized PnL sum: ${realized:+.2f}")
    print(f"  expected current_capital: ${expected_current:.2f}")

    delta = round(expected_current - current_now, 2)
    print(f"  delta to apply: ${delta:+.2f}")

    if abs(delta) < 0.01:
        print("\n  Already in sync, no update needed.")
        return

    new_peak = max(peak_now, expected_current)
    try:
        client.table("portfolio_state_ct").update({
            "current_capital": expected_current,
            "peak_capital": new_peak,
        }).eq("run_id", RUN_SCALPER).eq("strategy", "SCALPER").eq("is_shadow", False).execute()
        print(f"\n  ✓ Updated current_capital → ${expected_current:.2f}")
        print(f"  ✓ Updated peak_capital    → ${new_peak:.2f}")
    except Exception as e:
        print(f"  ✗ failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
