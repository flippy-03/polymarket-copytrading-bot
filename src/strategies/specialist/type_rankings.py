"""
Market type rankings aggregation (spec §6).

Recomputes spec_market_type_rankings from spec_type_activity data.
Called every TYPE_RECOMPUTE_INTERVAL_HOURS (default 6h).

Priority score formula:
  50% top_hit_rate (normalised 55%-80% → 0-1)
  30% avg_hit_rate (normalised 52%-68% → 0-1)
  10% n_specialists (3 = 0.3, 10+ = 1.0)
  10% recency (all ≥1 active in last 14 days)
"""
from __future__ import annotations

import time
from collections import defaultdict

from src.db import supabase_client as _db
from src.strategies.common import config as C
from src.utils.logger import logger


def recompute_all_type_rankings() -> dict[str, float]:
    """
    Read spec_type_activity, aggregate per market_type, write to
    spec_market_type_rankings. Returns {market_type: priority_score}.
    """
    client = _db.get_client()
    now = int(time.time())
    recency_cutoff = now - 14 * 86400

    try:
        rows = (
            client.table("spec_type_activity")
            .select("wallet, market_type, trades, wins, hit_rate, last_active_ts")
            .gte("trades", C.TYPE_MIN_SPECIALISTS_TO_RANK)
            .gte("hit_rate", C.SPEC_MIN_HIT_RATE)
            .execute()
            .data
        )
    except Exception as e:
        logger.warning(f"type_rankings: failed to fetch spec_type_activity: {e}")
        return {}

    # Aggregate per type
    agg: dict[str, dict] = defaultdict(lambda: {
        "hit_rates": [],
        "total_trades": 0,
        "recent_count": 0,
    })
    for row in rows:
        mtype = row["market_type"]
        hr = float(row.get("hit_rate") or 0)
        agg[mtype]["hit_rates"].append(hr)
        agg[mtype]["total_trades"] += int(row.get("trades") or 0)
        if int(row.get("last_active_ts") or 0) >= recency_cutoff:
            agg[mtype]["recent_count"] += 1

    scores: dict[str, float] = {}

    for mtype, data in agg.items():
        hrs = data["hit_rates"]
        n = len(hrs)
        if n < C.TYPE_MIN_SPECIALISTS_TO_RANK:
            continue

        top_hr = max(hrs)
        avg_hr = sum(hrs) / n
        total_trades = data["total_trades"]
        recent = data["recent_count"]

        # Normalise
        top_hr_norm = min(max((top_hr - 0.55) / (0.80 - 0.55), 0.0), 1.0)
        avg_hr_norm = min(max((avg_hr - 0.52) / (0.68 - 0.52), 0.0), 1.0)
        diversity_score = min(n / 10, 1.0)
        recency_score = min(recent / max(n, 1), 1.0)

        priority = (
            top_hr_norm * 0.50
            + avg_hr_norm * 0.30
            + diversity_score * 0.10
            + recency_score * 0.10
        )
        scores[mtype] = round(priority, 4)

        ranking_row = {
            "market_type": mtype,
            "n_specialists": n,
            "avg_hit_rate": round(avg_hr, 4),
            "top_hit_rate": round(top_hr, 4),
            "total_trades": total_trades,
            "priority_score": round(priority, 4),
            "last_updated_ts": now,
        }
        try:
            client.table("spec_market_type_rankings").upsert(
                ranking_row, on_conflict="market_type"
            ).execute()
        except Exception as e:
            logger.warning(f"  type_rankings upsert {mtype}: {e}")

    logger.info(
        f"type_rankings: recomputed {len(scores)} types: "
        + ", ".join(f"{k}={v:.3f}" for k, v in sorted(scores.items(), key=lambda x: -x[1])[:5])
    )
    return scores


def get_type_priority(universe_market_types: list[str]) -> list[tuple[str, float]]:
    """
    Fetch priority scores for a set of market types, sorted DESC.
    Returns [(market_type, priority_score), ...].
    Falls back to equal priority (0.5) for unknown types.
    """
    client = _db.get_client()
    try:
        result = (
            client.table("spec_market_type_rankings")
            .select("market_type, priority_score")
            .in_("market_type", universe_market_types)
            .execute()
        )
        known = {r["market_type"]: float(r["priority_score"]) for r in result.data}
    except Exception as e:
        logger.debug(f"  get_type_priority: {e}")
        known = {}

    out = [
        (mtype, known.get(mtype, 0.5))
        for mtype in universe_market_types
    ]
    return sorted(out, key=lambda x: -x[1])
