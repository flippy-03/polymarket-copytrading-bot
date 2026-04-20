"""Retrofit the Detroit Tigers real trades that opened against a broken CB.

Background:
  0x146703a8 was marked per_trader_is_broken=True at 2026-04-20 02:20
  (closing trade: Utah vs Golden Knights, 2nd consecutive loss hitting the
  per-titular limit). It should not have opened any further REAL trade.
  But due to the force_shadow propagation bug, two Detroit Tigers trades
  opened as real at 12:51 and 13:23 and closed at 16:33 with −11.4% each.

  With the bug fixed (commit fc0a8e9), those would have stayed shadow.
  Cleaning them up retroactively so the weekly backtest reflects the
  corrected behaviour.

Action:
  1. Find the 2 real + 2 shadow Detroit Tigers rows.
  2. The shadow rows already exist (open_paper_trade always opens both).
     So we don't need to CONVERT real to shadow; we just delete the real
     rows and fix the portfolio accounting.
  3. Reverse the portfolio mutations that apply_trade_to_portfolio made
     when those real rows closed:
       current_capital -= sum(real_pnl_usd)   # undo realized PnL
     Shadow portfolio is untouched because those shadows already got
     their own independent accounting.
  4. Leave the already-existing shadow rows intact — they reflect what
     SHOULD have happened.

DRY-RUN by default; --apply commits.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN = "b4a40e7d-50ec-476f-9765-e4fbab02608e"
WALLET = "0x146703a88a9d64a3ff21e0adb97f98c55bfd18e7"   # real hex — will be resolved
MARKET_QUESTION_LIKE = "Detroit Tigers vs. Boston Red Sox"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = _db.get_client()

    rows = (
        client.table("copy_trades")
        .select("id,source_wallet,is_shadow,status,pnl_usd,pnl_pct,"
                "close_reason,opened_at,closed_at,market_question,position_usd")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .ilike("market_question", f"%{MARKET_QUESTION_LIKE}%")
        .order("opened_at", desc=False)
        .execute()
        .data
    ) or []

    print(f"Found {len(rows)} Detroit Tigers rows in v3.0 SCALPER:\n")
    for r in rows:
        kind = "shadow" if r.get("is_shadow") else "REAL"
        print(f"  {r['id'][:8]} | {kind:6} | status={r['status']:6} | "
              f"wallet={(r['source_wallet'] or '—')[:10]} | "
              f"opened={r['opened_at'][:16]} | pnl={r.get('pnl_usd')} | "
              f"reason={r.get('close_reason')}")

    real_rows = [r for r in rows if not r.get("is_shadow")]
    shadow_rows = [r for r in rows if r.get("is_shadow")]

    print(f"\n  real: {len(real_rows)}  shadow: {len(shadow_rows)}")
    if len(real_rows) == 0:
        print("  Nothing to retrofit.")
        return
    if len(shadow_rows) == 0:
        print("  WARNING: no shadow counterparts found — deleting real rows\n"
              "           would lose the observation record. Aborting.")
        sys.exit(2)

    reverse_pnl = sum(float(r.get("pnl_usd") or 0) for r in real_rows)
    print(f"\n  Sum of real PnL to reverse: {reverse_pnl:+.2f}")

    # Fetch current portfolio
    p = (
        client.table("portfolio_state_ct")
        .select("current_capital,peak_capital")
        .eq("run_id", RUN)
        .eq("strategy", "SCALPER")
        .eq("is_shadow", False)
        .limit(1)
        .execute()
        .data
    )
    if not p:
        print("  WARNING: no portfolio row found.")
        return
    cur = float(p[0]["current_capital"] or 0)
    peak = float(p[0]["peak_capital"] or 0)
    new_cur = round(cur - reverse_pnl, 2)
    new_peak = max(peak, new_cur)
    print(f"\n  current_capital: ${cur:.2f} → ${new_cur:.2f}  (delta {-reverse_pnl:+.2f})")
    print(f"  peak_capital:    ${peak:.2f} → ${new_peak:.2f}")

    if not args.apply:
        print("\n  (dry-run — pass --apply to commit)")
        return

    print("\n=== APPLYING ===")
    # Delete the real rows
    for r in real_rows:
        try:
            client.table("copy_trades").delete().eq("id", r["id"]).execute()
            print(f"  ✓ deleted real {r['id'][:8]}")
        except Exception as e:
            print(f"  ✗ delete real {r['id'][:8]} failed: {e}")
            sys.exit(3)

    # Reconcile portfolio
    try:
        client.table("portfolio_state_ct").update({
            "current_capital": new_cur,
            "peak_capital": new_peak,
        }).eq("run_id", RUN).eq("strategy", "SCALPER").eq("is_shadow", False).execute()
        print(f"  ✓ portfolio current_capital → ${new_cur:.2f}")
    except Exception as e:
        print(f"  ✗ portfolio update failed: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
