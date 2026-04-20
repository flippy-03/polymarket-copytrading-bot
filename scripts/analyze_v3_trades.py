"""Deep-dive diagnostic on the v3.0 SCALPER run.

Questions to answer:
  1. Duplicate Magic vs Pistons — are they from different titulars
     (expected per-wallet behaviour) or the same (real bug)?
  2. Aggregate PnL, WR, win/loss breakdown for v3.0 so far.
  3. Verify that v3.0 fixes are active: no crypto_updown_micro trades,
     no unclassified trades, all have market_category set, all have
     source_wallet, all reals have EV>0 in metadata.
"""
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db

RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"


def main() -> None:
    client = _db.get_client()

    all_trades = (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,direction,entry_price,exit_price,"
                "position_usd,pnl_usd,pnl_pct,close_reason,status,is_shadow,"
                "opened_at,closed_at,market_category,metadata")
        .eq("run_id", RUN_SCALPER)
        .eq("strategy", "SCALPER")
        .order("opened_at", desc=True)
        .execute()
        .data
    )

    reals = [t for t in all_trades if not t["is_shadow"]]
    shadows = [t for t in all_trades if t["is_shadow"]]
    closed_reals = [t for t in reals if t["status"] == "CLOSED"]
    open_reals = [t for t in reals if t["status"] == "OPEN"]

    print("=" * 72)
    print("SCALPER v3.0  run=b4a40e7d")
    print("=" * 72)
    print(f"Total trades:    {len(all_trades)}  "
          f"(reales:{len(reals)}  shadow:{len(shadows)})")
    print(f"Real cerrados:   {len(closed_reals)}")
    print(f"Real abiertos:   {len(open_reals)}")

    # PnL aggregate
    total_pnl = sum(float(t["pnl_usd"] or 0) for t in closed_reals)
    wins = [t for t in closed_reals if float(t["pnl_usd"] or 0) > 0]
    losses = [t for t in closed_reals if float(t["pnl_usd"] or 0) <= 0]
    wr = len(wins) / len(closed_reals) if closed_reals else 0
    print(f"PnL total real:  ${total_pnl:+.2f}")
    print(f"WR real:         {wr:.0%}  ({len(wins)}W / {len(losses)}L)")

    print("\n=== TRADES REALES CERRADOS (detalle) ===")
    for t in closed_reals:
        meta = t.get("metadata") or {}
        mq = (t["market_question"] or "")[:40]
        wa = t["source_wallet"][:10] if t.get("source_wallet") else "?"
        ts_close = (t.get("closed_at") or "")[:16]
        print(f"  {ts_close} | {wa}.. | {mq:40} | "
              f"{t['direction']} ${t['entry_price']}->{t['exit_price']} | "
              f"PnL:${float(t['pnl_usd'] or 0):+.2f} "
              f"({float(t['pnl_pct'] or 0)*100:+.1f}%) | "
              f"{t['close_reason']}")

    # Duplicate detection
    print("\n=== BUSCAR DUPLICADOS POR MERCADO ===")
    by_market = defaultdict(list)
    for t in closed_reals + open_reals:
        mq = t["market_question"] or "?"
        by_market[mq].append(t)
    for mq, trades in by_market.items():
        if len(trades) > 1:
            print(f"\n  {mq[:60]}")
            for t in trades:
                wa = t["source_wallet"][:10] if t.get("source_wallet") else "?"
                ts = (t.get("opened_at") or "")[:16]
                cid = (t.get("metadata") or {}).get("titular")
                token = t.get("metadata", {}).get("market_type", "?")
                print(f"    id={t['id'][:8]} wallet={wa}.. opened={ts} "
                      f"entry={t['entry_price']} "
                      f"status={t['status']} type={token}")

    # Health checks
    print("\n=== VERIFICACION DE FIXES v3.0 ===")
    bad_type = [t for t in reals if (t.get("market_category") or "") in (
        "crypto_updown_micro", "crypto_updown_short", "unclassified", "other", "", None)]
    print(f"Trades reales con market_category vacio o bloqueado: {len(bad_type)}")
    for t in bad_type[:5]:
        print(f"  id={t['id'][:8]} cat={t.get('market_category')!r} mq={t['market_question'][:50]}")

    missing_wallet = [t for t in reals if not t.get("source_wallet")]
    print(f"Trades reales sin source_wallet: {len(missing_wallet)}")

    negative_ev_entries = []
    for t in reals:
        meta = t.get("metadata") or {}
        hr = meta.get("avg_hit_rate")
        entry = float(t.get("entry_price") or 0)
        if hr is not None and entry > 0:
            ev = float(hr) - entry
            if ev < 0:
                negative_ev_entries.append((t, ev))
    print(f"Trades reales con EV<0 en entrada: {len(negative_ev_entries)}")

    # Counts by close_reason
    reasons = Counter(t["close_reason"] for t in closed_reals)
    print(f"\nDistribucion close_reason (reales): {dict(reasons)}")

    # MARKET_RESOLVED losses — exposure correlacionada?
    mr_losses = [t for t in closed_reals if t["close_reason"] == "MARKET_RESOLVED"
                 and float(t["pnl_usd"] or 0) < 0]
    print(f"Trades MARKET_RESOLVED perdedores: {len(mr_losses)}")
    for t in mr_losses:
        wa = t["source_wallet"][:10] if t.get("source_wallet") else "?"
        print(f"  {wa}.. | {t['market_question'][:50]} | ${float(t['pnl_usd'] or 0):+.2f}")


if __name__ == "__main__":
    main()
