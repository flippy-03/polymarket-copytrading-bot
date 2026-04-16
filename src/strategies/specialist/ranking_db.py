"""
Ranking DB operations for Specialist Edge (spec §5).

Tables used: spec_ranking, spec_markets, spec_type_activity.
All writes use upsert (on-conflict update) to keep the pipeline idempotent.
"""
from __future__ import annotations

import time
from typing import Optional

from src.db import supabase_client as _db
from src.strategies.common import config as C
from src.strategies.specialist.specialist_profiler import SpecialistProfile
from src.utils.logger import logger


# ── Upsert / insert ──────────────────────────────────────

def upsert_profile(profile: SpecialistProfile, run_id: str) -> None:
    """Persist or update a SpecialistProfile in spec_ranking + type tables."""
    now_ts = int(time.time())
    client = _db.get_client()

    # spec_ranking upsert
    row = {
        "wallet": profile.address,
        "universe": profile.universe,
        "hit_rate": round(profile.universe_hit_rate, 4),
        "universe_trades": profile.universe_trades,
        "universe_wins": profile.universe_wins,
        "specialist_score": round(profile.specialist_score, 4),
        "current_streak": profile.current_streak,
        "last_active_ts": profile.last_active_ts,
        "avg_position_usd": round(profile.avg_position_usd, 2),
        "is_bot": profile.is_bot,
        "last_updated_ts": now_ts,
        "run_id": run_id,
    }
    # Set first_seen_ts only on INSERT (conflict → keep original)
    existing = (
        client.table("spec_ranking")
        .select("first_seen_ts")
        .eq("wallet", profile.address)
        .eq("universe", profile.universe)
        .limit(1)
        .execute()
        .data
    )
    if not existing:
        row["first_seen_ts"] = now_ts

    try:
        client.table("spec_ranking").upsert(row, on_conflict="wallet,universe").execute()
    except Exception as e:
        logger.warning(f"  upsert_profile {profile.address[:10]}… failed: {e}")
        return

    # spec_type_activity upsert
    for mtype, act in profile.all_type_activity.items():
        ta_row = {
            "wallet": profile.address,
            "market_type": mtype,
            "trades": act.trades,
            "wins": act.wins,
            "hit_rate": round(act.hit_rate, 4),
            "avg_position_usd": round(act.avg_position_usd, 2),
            "last_active_ts": act.last_active_ts,
            "last_30d_trades": act.recent_30d_trades,
        }
        try:
            client.table("spec_type_activity").upsert(
                ta_row, on_conflict="wallet,market_type"
            ).execute()
        except Exception as e:
            logger.debug(f"  upsert_type_activity {mtype}: {e}")

    # Renumber positions in this universe
    _renumber_positions(profile.universe)


def record_market_seen(
    wallet: str,
    universe: str,
    condition_id: str,
    side: Optional[str] = None,
) -> None:
    """Record that we've seen a wallet in a specific market (for audit/routing)."""
    client = _db.get_client()
    try:
        client.table("spec_markets").upsert(
            {
                "wallet": wallet,
                "universe": universe,
                "condition_id": condition_id,
                "side": side,
                "first_seen_ts": int(time.time()),
            },
            on_conflict="wallet,condition_id",
        ).execute()
    except Exception as e:
        logger.debug(f"  record_market_seen: {e}")


# ── Queries ──────────────────────────────────────────────

def get_known_specialists(
    universe: str,
    min_hit_rate: float = C.SPEC_MIN_HIT_RATE,
    max_age_hours: float = C.HYBRID_BD_ONLY_MAX_AGE_HOURS,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch known specialists for a universe, filtered by hit rate and recency.
    Returns rows sorted by specialist_score DESC.
    """
    stale_cutoff = int(time.time()) - int(max_age_hours * 3600)
    client = _db.get_client()
    try:
        result = (
            client.table("spec_ranking")
            .select("wallet, universe, hit_rate, specialist_score, universe_trades, "
                    "current_streak, last_active_ts, avg_position_usd, last_updated_ts")
            .eq("universe", universe)
            .gte("hit_rate", min_hit_rate)
            .gte("last_updated_ts", stale_cutoff)
            .order("specialist_score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"  get_known_specialists({universe}): {e}")
        return []


def get_type_activity(
    wallet: str,
    market_type: str,
) -> Optional[dict]:
    """Fetch type-specific activity for a wallet."""
    client = _db.get_client()
    try:
        result = (
            client.table("spec_type_activity")
            .select("*")
            .eq("wallet", wallet)
            .eq("market_type", market_type)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def list_ranking(universe: str, limit: int = 20) -> list[dict]:
    """Return top specialists for a universe, ordered by rank_position."""
    client = _db.get_client()
    try:
        result = (
            client.table("spec_ranking")
            .select("*")
            .eq("universe", universe)
            .order("specialist_score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"  list_ranking({universe}): {e}")
        return []


def get_stale_profiles(
    max_age_hours: float = 24,
    batch_size: int = 20,
) -> list[dict]:
    """Return profiles that haven't been updated in max_age_hours, for refresh."""
    stale_cutoff = int(time.time()) - int(max_age_hours * 3600)
    client = _db.get_client()
    try:
        result = (
            client.table("spec_ranking")
            .select("wallet, universe, specialist_score")
            .lt("last_updated_ts", stale_cutoff)
            .order("specialist_score", desc=True)
            .limit(batch_size)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"  get_stale_profiles: {e}")
        return []


def count_ranking(universe: str) -> int:
    """Count specialists in a universe's ranking."""
    client = _db.get_client()
    try:
        result = (
            client.table("spec_ranking")
            .select("wallet", count="exact")
            .eq("universe", universe)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0


# ── Internal helpers ──────────────────────────────────────

def _renumber_positions(universe: str) -> None:
    """
    Update rank_position (1..N) by specialist_score DESC for a universe.
    Called after every upsert to keep positions fresh.
    """
    client = _db.get_client()
    try:
        rows = (
            client.table("spec_ranking")
            .select("wallet, universe")
            .eq("universe", universe)
            .order("specialist_score", desc=True)
            .execute()
            .data
        )
        for i, row in enumerate(rows, start=1):
            client.table("spec_ranking").update({"rank_position": i}).eq(
                "wallet", row["wallet"]
            ).eq("universe", row["universe"]).execute()
    except Exception as e:
        logger.debug(f"  _renumber_positions({universe}): {e}")


def remove_profile(wallet: str, universe: str) -> None:
    """Remove a wallet from a universe ranking (no longer qualifies)."""
    client = _db.get_client()
    try:
        client.table("spec_ranking").delete().eq("wallet", wallet).eq(
            "universe", universe
        ).execute()
        _renumber_positions(universe)
    except Exception as e:
        logger.debug(f"  remove_profile({wallet[:10]}…, {universe}): {e}")
