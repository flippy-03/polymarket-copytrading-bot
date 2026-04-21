"""End-of-day performance check for both strategies in run v3.0.

Reports, per strategy:
  - Portfolio state (current / peak / realized PnL / drawdown)
  - Open positions count
  - Recent closed trades (full detail)
  - Close-reason distribution
  - WR and category breakdown
  - Sanity checks on v3.1 fixes:
      • No real trade opened from a broken titular
      • No duplicated (event_slug, direction) on real side
      • No real trade closed at worse than category hard stop
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


RUN_SCALPER = "b4a40e7d-50ec-476f-9765-e4fbab02608e"
RUN_SPECIALIST = "b3af0daf-b4a4-48b7-b5e5-cd4ac01af0ad"   # best guess
_SPORTS = {"sports_winner", "sports_spread", "sports_total", "sports_futures"}


def pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x*100:+.1f}%"


def analyse_strategy(client, run_id: str, strategy: str) -> None:
    print(f"\n{'=' * 78}")
    print(f"{strategy} · run={run_id[:8]}")
    print("=" * 78)

    # Portfolio
    p = (
        client.table("portfolio_state_ct")
        .select("*")
        .eq("run_id", run_id)
        .eq("strategy", strategy)
        .eq("is_shadow", False)
        .limit(1)
        .execute()
        .data
    )
    if not p:
        print("  (no portfolio row — run may not exist)")
        return
    p = p[0]
    init = float(p.get("initial_capital") or 0)
    cur = float(p.get("current_capital") or 0)
    peak = float(p.get("peak_capital") or init)
    dd = (peak - cur) / peak * 100 if peak else 0
    print(f"  Capital: initial=${init:.2f}  current=${cur:.2f}  peak=${peak:.2f}")
    print(f"  Realized PnL: ${cur-init:+.2f}  ({(cur-init)/init*100:+.2f}%)")
    print(f"  Drawdown from peak: {dd:.2f}%")
    print(f"  Open positions: {p.get('open_positions')}/{p.get('max_open_positions')}")
    print(f"  consecutive_losses: {p.get('consecutive_losses')}  "
          f"CB broken: {p.get('is_circuit_broken')}")

    # All trades
    trades = (
        client.table("copy_trades")
        .select("id,source_wallet,market_question,market_category,is_shadow,"
                "direction,entry_price,exit_price,position_usd,pnl_usd,pnl_pct,"
                "close_reason,status,opened_at,closed_at,metadata")
        .eq("run_id", run_id)
        .eq("strategy", strategy)
        .order("opened_at", desc=True)
        .execute()
        .data
    ) or []
    real = [t for t in trades if not t["is_shadow"]]
    shadow = [t for t in trades if t["is_shadow"]]
    real_closed = [t for t in real if t["status"] == "CLOSED"]
    real_open = [t for t in real if t["status"] == "OPEN"]
    print(f"\n  Trades: real={len(real)} (closed={len(real_closed)}, open={len(real_open)}) "
          f"| shadow={len(shadow)}")

    if not real_closed and not real_open:
        return

    # Close-reason distribution (real)
    reasons = Counter(t.get("close_reason") or "—" for t in real_closed)
    print(f"  Close reasons (real): {dict(reasons)}")

    # WR, avg win / avg loss
    wins = [t for t in real_closed if float(t.get("pnl_usd") or 0) > 0]
    losses = [t for t in real_closed if float(t.get("pnl_usd") or 0) <= 0]
    total = len(real_closed)
    if total > 0:
        wr = len(wins) / total * 100
        avg_win = sum(float(t["pnl_usd"]) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(float(t["pnl_usd"]) for t in losses) / len(losses) if losses else 0
        biggest_win = max((float(t["pnl_usd"]) for t in wins), default=0)
        biggest_loss = min((float(t["pnl_usd"]) for t in losses), default=0)
        print(f"  WR: {wr:.0f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  Avg win: ${avg_win:+.2f}  |  Avg loss: ${avg_loss:+.2f}")
        print(f"  Biggest win: ${biggest_win:+.2f}  |  Biggest loss: ${biggest_loss:+.2f}")

    # Category breakdown (real closed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for t in real_closed:
        cat = t.get("market_category") or (t.get("metadata") or {}).get("market_type") or "—"
        by_cat[cat].append(t)
    if by_cat:
        print(f"\n  Real closed by category:")
        for cat, ts in by_cat.items():
            n = len(ts)
            pnl = sum(float(x.get("pnl_usd") or 0) for x in ts)
            ws = sum(1 for x in ts if float(x.get("pnl_usd") or 0) > 0)
            print(f"    {cat:<25} n={n:>3}  PnL=${pnl:+8.2f}  WR={ws/n*100:.0f}%")

    # Recent real closed trades (top 10)
    print(f"\n  Last 10 real closed (newest first):")
    for t in real_closed[:10]:
        mq = (t.get("market_question") or "")[:40]
        cat = t.get("market_category") or "—"
        ts = (t.get("closed_at") or "")[:16].replace("T", " ")
        pnl = float(t.get("pnl_usd") or 0)
        reason = t.get("close_reason")
        print(f"    {ts} | {mq:<40} | {cat:<22} | "
              f"{t['direction']} ${t['entry_price']:.2f}->{t['exit_price']:.2f} | "
              f"${pnl:+.2f} ({pct(float(t.get('pnl_pct') or 0))}) | {reason}")

    # ─── SANITY CHECKS ──────────────────────────────────────────────────────
    print(f"\n  --- SANITY CHECKS ---")

    # 1. No real trade opened from a broken titular (only SCALPER)
    if strategy == "SCALPER":
        pool = (
            client.table("scalper_pool")
            .select("wallet_address,per_trader_is_broken")
            .eq("run_id", run_id)
            .execute()
            .data
        ) or []
        broken_wallets = {p["wallet_address"] for p in pool if p.get("per_trader_is_broken")}
        violators = []
        for t in real:
            if t.get("source_wallet") in broken_wallets:
                wallet_break_time = None
                # We need to know when it broke — use the opened_at comparison
                # as "if any real post 02:20 from a broken wallet"; we already
                # removed the Detroit Tigers manually, so new violations
                # would mean the fix isn't working.
                violators.append(t)
        if violators:
            print(f"  ⚠️  Broken titulars opened real trades: {len(violators)}")
            for v in violators[:5]:
                print(f"      {v['id'][:8]} wallet={v['source_wallet'][:10]}.. "
                      f"opened={v['opened_at'][:16]} status={v['status']}")
        else:
            print(f"  ✓ No real trades from broken titulars "
                  f"(broken wallets: {len(broken_wallets)})")

    # 2. No duplicated (event_slug, direction) on real side
    if strategy == "SCALPER":
        by_ev = defaultdict(list)
        for t in real:
            meta = t.get("metadata") or {}
            ev = meta.get("event_slug")
            if ev:
                by_ev[(ev, t.get("direction"))].append(t)
        dupes = {k: v for k, v in by_ev.items() if len(v) > 1}
        if dupes:
            print(f"  ⚠️  Duplicated (event_slug, direction) on real: {len(dupes)}")
            for (ev, direction), ts in list(dupes.items())[:3]:
                print(f"      event={ev[:30]} dir={direction} x{len(ts)}")
        else:
            print(f"  ✓ No duplicated (event, direction) on real side")

    # 3. Real trades closed below the category hard stop
    if strategy == "SCALPER":
        too_deep = []
        for t in real_closed:
            mtype = (t.get("metadata") or {}).get("market_type") or t.get("market_category")
            hs = -0.40 if mtype in _SPORTS else -0.20
            pnl_pct = float(t.get("pnl_pct") or 0)
            if pnl_pct < hs - 0.01 and t.get("close_reason") not in (
                "STOP_LOSS_RETROFIT", "MARKET_RESOLVED"):
                # Ignore RETROFIT (manual data cleanup) and MARKET_RESOLVED
                # (the market resolved before the bot could act).
                too_deep.append((t, hs))
        if too_deep:
            print(f"  ⚠️  Real trades closed deeper than their hard stop: {len(too_deep)}")
            for t, hs in too_deep[:5]:
                print(f"      {t['id'][:8]} {t.get('market_question','')[:30]} "
                      f"pnl={pct(float(t['pnl_pct']))} hs={pct(hs)} "
                      f"reason={t.get('close_reason')}")
        else:
            print(f"  ✓ All real closes within the category hard stop "
                  f"(sports -40%, rest -20%)")


def find_specialist_run(client) -> str | None:
    """Try to identify the current v3.0 SPECIALIST run."""
    rows = (
        client.table("runs")
        .select("id,version,strategy,started_at,status")
        .eq("strategy", "SPECIALIST")
        .eq("status", "ACTIVE")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
        .data
    ) or []
    if rows:
        return rows[0]["id"]
    return None


def main() -> None:
    client = _db.get_client()

    analyse_strategy(client, RUN_SCALPER, "SCALPER")

    specialist_run = find_specialist_run(client)
    if specialist_run:
        analyse_strategy(client, specialist_run, "SPECIALIST")
    else:
        print("\n(no active SPECIALIST run found — skipping)")


if __name__ == "__main__":
    main()
