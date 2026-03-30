"""
health_check.py — Bot status snapshot

Verifica en una sola pasada el estado del bot:
  - Portfolio (capital, WR, drawdown, circuit breaker)
  - Posiciones reales abiertas
  - Shadow trades abiertos y estadísticas acumuladas
  - Actividad reciente (señales y trades últimas 24h)
  - Frescura del collector (último snapshot)
  - Tabla shadow_trades presente (migración aplicada)

Usage:
    PYTHONPATH=. python scripts/health_check.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from datetime import datetime, timezone, timedelta
from src.db import supabase_client as db


def ts_ago(iso_str: str) -> str:
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(tz=timezone.utc) - dt).total_seconds()
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        if h >= 24:
            return f"{h//24}d {h%24}h ago"
        return f"{h}h {m}m ago" if h else f"{m}m ago"
    except Exception:
        return iso_str[:16]


def run():
    print("=" * 58)
    print("  POLYMARKET BOT — HEALTH CHECK")
    print(f"  {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 58)

    try:
        client = db.get_client()
        client.table("markets").select("id").limit(1).execute()
    except Exception as e:
        print(f"\n  DB: FAIL — {e}")
        sys.exit(1)

    # ── Portfolio ──────────────────────────────────────────────────
    print("\n[ PORTFOLIO ]")
    port = client.table("portfolio_state").select("*").order("run_id", desc=True).limit(1).execute().data
    if not port:
        print("  Sin datos de portfolio")
    else:
        p = port[0]
        cb = "BLOQUEADO" if p.get("is_circuit_broken") else "OK"
        cb_extra = f" hasta {p['circuit_broken_until'][:16]}" if p.get("is_circuit_broken") else ""
        print(f"  Capital:      ${p['current_capital']:,.2f}  ({p['total_pnl_pct']*100:+.1f}%)")
        print(f"  P&L total:    ${p['total_pnl']:+.2f}")
        print(f"  Win rate:     {p['win_rate']*100:.0f}%  ({p['winning_trades']}W / {p['losing_trades']}L)")
        print(f"  Trades:       {p['total_trades']} total  |  {p['open_positions']}/{p['max_open_positions']} abiertas")
        print(f"  Max drawdown: {p['max_drawdown']*100:.1f}%")
        print(f"  Circuit:      {cb}{cb_extra}")

    # ── Posiciones reales abiertas ─────────────────────────────────
    print("\n[ POSICIONES ABIERTAS ]")
    open_trades = (
        client.table("paper_trades")
        .select("id, direction, entry_price, position_usd, opened_at, market_id")
        .eq("status", "OPEN")
        .execute()
        .data
    )
    if not open_trades:
        print("  Ninguna")
    else:
        for t in open_trades:
            print(f"  {t['id'][:8]}  {t['direction']} @ {t['entry_price']}  ${t['position_usd']:.0f}  ({ts_ago(t['opened_at'])})")

    # ── Shadow trades ──────────────────────────────────────────────
    print("\n[ SHADOW TRADES ]")
    try:
        open_sh = client.table("shadow_trades").select("*").eq("status", "OPEN").execute().data
        closed_sh = client.table("shadow_trades").select("pnl_usd, close_reason, blocked_reason").eq("status", "CLOSED").execute().data

        print(f"  Abiertos: {len(open_sh)}")
        for s in open_sh:
            print(f"    {s['id'][:8]}  {s['direction']} @ {s['entry_price']}  bloqueado: {s.get('blocked_reason','?')}  ({ts_ago(s.get('entry_at'))})")

        if closed_sh:
            wins = sum(1 for s in closed_sh if s.get("pnl_usd") and float(s["pnl_usd"]) > 0)
            total_pnl = sum(float(s["pnl_usd"]) for s in closed_sh if s.get("pnl_usd"))
            wr = wins / len(closed_sh) * 100
            reasons = dict(Counter(s.get("close_reason", "?") for s in closed_sh))
            print(f"  Cerrados: {len(closed_sh)}  |  WR: {wr:.0f}%  |  P&L: ${total_pnl:+.2f}")
            print(f"  Cierres:  {reasons}")
        else:
            print("  Cerrados: 0")
    except Exception:
        print("  Tabla shadow_trades no existe — ejecutar setup_shadow_trades.sql en Supabase")

    # ── Actividad últimas 24h ──────────────────────────────────────
    print("\n[ ÚLTIMAS 24H ]")
    since = (datetime.now(tz=timezone.utc) - timedelta(hours=24)).isoformat()

    signals_24h = (
        client.table("signals")
        .select("status, direction")
        .gte("created_at", since)
        .execute()
        .data
    )
    trades_24h = (
        client.table("paper_trades")
        .select("status, direction, pnl_usd, close_reason")
        .gte("opened_at", since)
        .execute()
        .data
    )

    if signals_24h:
        by_status = dict(Counter(s["status"] for s in signals_24h))
        by_dir = dict(Counter(s["direction"] for s in signals_24h))
        print(f"  Señales:  {len(signals_24h)}  {by_status}  dirs: {by_dir}")
    else:
        print("  Señales:  0")

    opened_24h = [t for t in trades_24h if t["status"] == "OPEN"]
    closed_24h = [t for t in trades_24h if t["status"] == "CLOSED"]
    print(f"  Trades abiertos: {len(opened_24h)}  |  cerrados: {len(closed_24h)}")
    for t in closed_24h:
        pnl = f"${float(t['pnl_usd']):+.2f}" if t.get("pnl_usd") else "?"
        print(f"    {t['direction']} — {t['close_reason']} {pnl}")

    # ── Collector ──────────────────────────────────────────────────
    print("\n[ COLLECTOR ]")
    last_snap = (
        client.table("market_snapshots")
        .select("snapshot_at")
        .order("snapshot_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if last_snap:
        snap_age = ts_ago(last_snap[0]["snapshot_at"])
        try:
            dt = datetime.fromisoformat(last_snap[0]["snapshot_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            stale = (datetime.now(tz=timezone.utc) - dt).total_seconds() > 600
        except Exception:
            stale = False
        print(f"  Último snapshot: {snap_age}  [{'WARN — collector caído?' if stale else 'OK'}]")
    else:
        print("  Último snapshot: NINGUNO")

    since_1h = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
    snaps_1h = len(client.table("market_snapshots").select("id").gte("snapshot_at", since_1h).execute().data)
    print(f"  Snapshots última hora: {snaps_1h}")

    # ── Resumen ────────────────────────────────────────────────────
    print("\n" + "=" * 58)
    issues = []
    try:
        client.table("shadow_trades").select("id").limit(1).execute()
    except Exception:
        issues.append("shadow_trades table falta")
    if last_snap:
        try:
            dt = datetime.fromisoformat(last_snap[0]["snapshot_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (datetime.now(tz=timezone.utc) - dt).total_seconds() > 600:
                issues.append("collector sin actividad >10min")
        except Exception:
            pass
    if port and port[0].get("is_circuit_broken"):
        issues.append("circuit breaker activo")

    status = f"WARN — {', '.join(issues)}" if issues else "TODO OK"
    print(f"  STATUS: {status}")
    print("=" * 58)


if __name__ == "__main__":
    run()
