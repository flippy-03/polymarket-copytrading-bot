"""One-shot: swap two scalper titulars and force-pin two new wallets.

Removes:
  - 0xc332b04ad3a187e3055f2db6cd55d692a68459a9 (sports_winner only, BROKEN)
  - 0x146703a8a73ae1dff0f84ba44c45d878858a4372 (sports_winner only, BROKEN, 0W/2L)

Adds (forced — no profile yet, copy all market types):
  - 0x50b1e35022933ae620665ce55dbd9785c5e30793
  - 0xf4b13fea865321d231b515e8786c62e6f561ab63

The forced flag exempts these titulars from rotation_engine degradation,
pool_selector retire-step, and the approved_market_types filter in
copy_monitor / scalper_executor. Risk and per-titular CB still apply.

PRE-REQUISITE: migration 019_v3_forced_titulars.sql must be applied first.
"""
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db
from src.strategies.common import db
from src.utils.logger import logger


REMOVE = [
    "0xc332b04ad3a187e3055f2db6cd55d692a68459a9",
    "0x146703a8a73ae1dff0f84ba44c45d878858a4372",
]

ADD_FORCED = [
    "0x50b1e35022933ae620665ce55dbd9785c5e30793",
    "0xf4b13fea865321d231b515e8786c62e6f561ab63",
]


def main() -> None:
    run_id = db.get_active_run("SCALPER")
    client = _db.get_client()
    logger.info(f"Active SCALPER run: {run_id}")

    # 1. Demote the two removed titulars to POOL.
    for w in REMOVE:
        client.table("scalper_pool").update({
            "status": "POOL",
            "capital_allocated_usd": 0,
            "allocation_pct": 0,
        }).eq("run_id", run_id).eq("wallet_address", w).execute()
        logger.info(f"  demoted {w[:10]}... -> POOL")

    # 2. Insert/upsert the two forced titulars.
    # No enriched profile yet, so:
    #   - approved_market_types = []  (irrelevant — is_forced bypasses filter)
    #   - composite_score      = 0.99 (synthetic high to satisfy any score gate)
    #   - validation_outcome   = "PROMOTED" (skip shadow window — operator pinned them)
    for w in ADD_FORCED:
        db.ensure_wallet(w)
        client.table("scalper_pool").upsert({
            "run_id": run_id,
            "wallet_address": w,
            "status": "ACTIVE_TITULAR",
            "is_forced": True,
            "approved_market_types": [],
            "composite_score": 0.99,
            "capital_allocated_usd": 0,
            "allocation_pct": 0.25,
            "per_trader_loss_limit": 4,
            "per_trader_consecutive_losses": 0,
            "per_trader_is_broken": False,
            "consecutive_wins": 0,
            "validation_outcome": "PROMOTED",
            "shadow_validation_until": None,
            "sizing_multiplier": 1.0,
        }, on_conflict="run_id,wallet_address").execute()
        logger.info(f"  forced ACTIVE_TITULAR {w[:10]}...")

    # 3. Re-balance allocation_pct to 0.25 across all 4 active titulars.
    actives = (
        client.table("scalper_pool")
        .select("wallet_address")
        .eq("run_id", run_id)
        .eq("status", "ACTIVE_TITULAR")
        .execute()
        .data
    )
    n = len(actives)
    if n == 0:
        logger.error("No active titulars after swap — bailing out without rebalance.")
        return
    pct = round(1.0 / n, 6)
    for row in actives:
        client.table("scalper_pool").update({"allocation_pct": pct}).eq(
            "run_id", run_id
        ).eq("wallet_address", row["wallet_address"]).execute()
    logger.info(f"  rebalanced allocation_pct={pct} across {n} titulars")

    # 4. Print final state.
    final = (
        client.table("scalper_pool")
        .select(
            "wallet_address,status,is_forced,composite_score,approved_market_types,"
            "allocation_pct,per_trader_is_broken,validation_outcome"
        )
        .eq("run_id", run_id)
        .eq("status", "ACTIVE_TITULAR")
        .execute()
        .data
    )
    print("\n=== Final ACTIVE_TITULARS ===")
    for r in final:
        print(
            f"  {r['wallet_address']}  forced={r['is_forced']}  "
            f"score={r['composite_score']}  alloc={r['allocation_pct']}  "
            f"types={r['approved_market_types']}  "
            f"broken={r['per_trader_is_broken']}  validation={r['validation_outcome']}"
        )


if __name__ == "__main__":
    main()
