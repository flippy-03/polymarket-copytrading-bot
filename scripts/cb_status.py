"""Diagnostic on circuit-breaker state for SCALPER v3.0.

Reports:
  - Global consecutive_losses counter in portfolio_state_ct
  - Is the global CB currently tripped?
  - Per-titular per_trader_consecutive_losses and per_trader_is_broken
  - SCALPER_CONSECUTIVE_LOSS_LIMIT config value (should be 6)
  - Chronological list of the last 15 closed trades with per-wallet
    consecutive_losses trajectory (simulated from the DB order)
"""
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db
from src.strategies.common import config as C


RUN = "b4a40e7d-50ec-476f-9765-e4fbab02608e"


def main() -> None:
    client = _db.get_client()

    # 1. Config thresholds
    print("=== CONFIG THRESHOLDS ===")
    print(f"  SCALPER_CONSECUTIVE_LOSS_LIMIT (global): {C.SCALPER_CONSECUTIVE_LOSS_LIMIT}")
    print(f"  loss_pct cutoff for streak: -0.02")

    # 2. Global portfolio state
    print("\n=== GLOBAL PORTFOLIO STATE (real) ===")
    p = (
        client.table("portfolio_state_ct")
        .select("consecutive_losses,is_circuit_broken,circuit_broken_until,"
                "requires_manual_review,current_capital,peak_capital,max_open_positions,open_positions")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .limit(1)
        .execute()
        .data
    )
    if p:
        print(f"  {p[0]}")

    # 3. Per-titular state
    print("\n=== PER-TITULAR STATE ===")
    pool = (
        client.table("scalper_pool")
        .select("wallet_address,per_trader_consecutive_losses,"
                "per_trader_is_broken,per_trader_loss_limit,consecutive_wins,"
                "sizing_multiplier,status")
        .eq("run_id", RUN)
        .eq("status", "ACTIVE_TITULAR")
        .execute()
        .data
    ) or []
    for x in pool:
        print(f"  {x['wallet_address'][:10]}.. losses={x.get('per_trader_consecutive_losses')} "
              f"broken={x.get('per_trader_is_broken')} "
              f"limit={x.get('per_trader_loss_limit')} "
              f"wins_streak={x.get('consecutive_wins')} "
              f"size_mult={x.get('sizing_multiplier')}")

    # 4. Simulated streak trajectory from closed real trades
    print("\n=== SIMULATED STREAK FROM CLOSED REAL TRADES (chronological) ===")
    trades = (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,pnl_usd,pnl_pct,close_reason,closed_at")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .eq("status", "CLOSED")
        .order("closed_at", desc=False)
        .execute()
        .data
    ) or []

    global_streak = 0
    per_titular_streak: dict[str, int] = defaultdict(int)
    max_global = 0
    max_titular: dict[str, int] = defaultdict(int)

    for t in trades:
        pct = float(t.get("pnl_pct") or 0)
        wallet = (t.get("source_wallet") or "")[:10]
        mq = (t.get("market_question") or "")[:35]
        reason = t.get("close_reason")
        ts = (t.get("closed_at") or "")[:16].replace("T", " ")
        if pct < -0.02:
            global_streak += 1
            per_titular_streak[wallet] += 1
        else:
            global_streak = 0
            per_titular_streak[wallet] = 0
        max_global = max(max_global, global_streak)
        max_titular[wallet] = max(max_titular[wallet], per_titular_streak[wallet])
        print(f"  {ts} | {wallet}.. | {mq:<36} | pnl={pct:+.1%} "
              f"| global_streak={global_streak} | titular_streak={per_titular_streak[wallet]} "
              f"| {reason}")

    print(f"\n  Max global streak observed: {max_global}")
    for w, n in max_titular.items():
        print(f"  Max titular streak {w}..: {n}")


if __name__ == "__main__":
    main()
