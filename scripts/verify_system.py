"""
Script de verificación del sistema — Fases B y C del plan.
Ejecutar via: python scripts/verify_system.py
"""
import os
from collections import Counter

os.environ.setdefault("SUPABASE_URL", "https://pdmmvhshorwfqseattvz.supabase.co")
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBkbW12aHNob3J3ZnFzZWF0dHZ6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDA0MjIzOCwiZXhwIjoyMDg5NjE4MjM4fQ.vghMxRIfG5bFK2YLoj7TwaWFpMnjlrGC6vyFNOuIqlA",
)

from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# ── Portfolio state (C1) ─────────────────────────────────
print("=== PORTFOLIO STATE ===")
rows = sb.table("portfolio_state_ct").select("*").execute()
if rows.data:
    for r in rows.data:
        print(
            f"  {r.get('strategy')} shadow={r.get('is_shadow')} "
            f"init=${r.get('initial_capital')} cur=${r.get('current_capital')} "
            f"open={r.get('open_positions')} updated={str(r.get('updated_at',''))[:19]}"
        )
else:
    print("  *** EMPTY — portfolio_state_ct no inicializado! CRÍTICO ***")

# ── Observed trades (B1) ─────────────────────────────────
print()
print("=== OBSERVED TRADES ===")
obs = sb.table("observed_trades").select("*", count="exact").limit(1).execute()
total_obs = obs.count or 0
print(f"  Total count: {total_obs}")
if total_obs > 0:
    latest = (
        sb.table("observed_trades")
        .select("observed_at,wallet_address")
        .order("observed_at", desc=True)
        .limit(5)
        .execute()
    )
    for r in latest.data:
        print(f"  {r['wallet_address'][:14]}… at {str(r['observed_at'])[:19]}")
else:
    print("  *** Sin registros — monitor no está guardando observaciones ***")

# ── Copy trades (C2) ─────────────────────────────────────
print()
print("=== COPY TRADES ===")
ct = sb.table("copy_trades").select("strategy,is_shadow,status,pnl_usd").execute()
if ct.data:
    groups: dict = {}
    for r in ct.data:
        key = (r["strategy"], r["is_shadow"], r["status"])
        if key not in groups:
            groups[key] = {"cnt": 0, "pnl": 0.0}
        groups[key]["cnt"] += 1
        groups[key]["pnl"] += float(r.get("pnl_usd") or 0)
    for (strat, shadow, status), v in sorted(groups.items()):
        print(f"  {strat} shadow={shadow} {status}: {v['cnt']} trades, pnl=${v['pnl']:.2f}")
    # Orphaned (open > 7 days) check
    stale = (
        sb.table("copy_trades")
        .select("id,strategy,opened_at")
        .eq("status", "OPEN")
        .execute()
    )
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    orphans = [r for r in (stale.data or []) if str(r.get("opened_at", "9999")) < cutoff]
    if orphans:
        print(f"  *** POSICIONES HUÉRFANAS (>7d open): {len(orphans)} ***")
        for r in orphans[:5]:
            print(f"    id={r['id']} strat={r['strategy']} opened={str(r['opened_at'])[:19]}")
    else:
        print("  Sin posiciones huérfanas (OK)")
else:
    print("  Sin copy_trades aún")

# ── Consensus signals (B2) ───────────────────────────────
print()
print("=== CONSENSUS SIGNALS ===")
cs = sb.table("consensus_signals").select("status").execute()
c2 = Counter(r["status"] for r in cs.data) if cs.data else {}
print(f"  {dict(c2) if c2 else 'Sin señales aún'}")

# ── Wallet metrics (A) ───────────────────────────────────
print()
print("=== WALLET METRICS (last 15) ===")
wm = (
    sb.table("wallet_metrics")
    .select("wallet_address,win_rate,pnl_30d,pnl_7d,total_trades,avg_position_size,tier1_pass")
    .order("snapshot_at", desc=True)
    .limit(15)
    .execute()
)
for r in wm.data:
    print(
        f"  {r['wallet_address'][:14]}… "
        f"WR={float(r['win_rate']):.1%} "
        f"pnl30=${float(r['pnl_30d']):.2f} "
        f"pnl7=${float(r['pnl_7d']):.2f} "
        f"trades={r['total_trades']} "
        f"size=${float(r['avg_position_size']):.0f} "
        f"T1={'OK' if r['tier1_pass'] else 'FAIL'}"
    )

# ── Scalper pool (B3) ────────────────────────────────────
print()
print("=== SCALPER POOL ===")
sp = sb.table("scalper_pool").select("address,status,sharpe_14d,rank_position").execute()
for r in (sp.data or []):
    print(
        f"  #{r.get('rank_position')} {r['address'][:14]}… "
        f"sharpe={r.get('sharpe_14d')} status={r.get('status')}"
    )

print()
print("VERIFICACION COMPLETA")
