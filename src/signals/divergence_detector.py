"""
Divergence detector — Phase 2 proxy strategy.

Since we don't have a direct AI-vs-Humans feed, we build a proxy:
  - Whale herding: consecutive whale trades in same direction = bots piling in
  - Price velocity: rapid price move in 1h = probable overshoot
  - Combined: herding + velocity aligned → contrarian opportunity
"""

from datetime import datetime, timezone, timedelta
from src.db import supabase_client as db
from src.utils.logger import logger


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_recent_snapshots(market_id: str, hours: int = 4) -> list:
    client = db.get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = (
        client.table("market_snapshots")
        .select("snapshot_at,yes_price,no_price,whale_direction,whale_trade_count,whale_volume_usd")
        .eq("market_id", market_id)
        .gte("snapshot_at", cutoff)
        .order("snapshot_at", desc=False)
        .execute()
    )
    return result.data


def detect_whale_herding(snapshots: list) -> dict:
    """
    Returns herding signal if whales consistently trade the same direction.
    Needs at least 2 snapshots with whale data.
    """
    whale_snaps = [s for s in snapshots if s.get("whale_direction") in ("YES", "NO")]

    if len(whale_snaps) < 2:
        return {"detected": False, "direction": None, "strength": 0.0, "sample_size": len(whale_snaps)}

    recent = whale_snaps[-5:]  # last 5 whale-active snapshots
    directions = [s["whale_direction"] for s in recent]
    total = len(directions)
    yes_count = directions.count("YES")
    no_count = directions.count("NO")

    if yes_count / total >= 0.80:
        return {"detected": True, "direction": "YES", "strength": yes_count / total, "sample_size": total}
    if no_count / total >= 0.80:
        return {"detected": True, "direction": "NO", "strength": no_count / total, "sample_size": total}

    return {"detected": False, "direction": None, "strength": 0.0, "sample_size": total}


def detect_price_velocity(snapshots: list) -> dict:
    """
    Calculate price change vs 1h ago and 4h ago.
    Rapid moves (>5% in 1h) are candidate contrarian entries.
    """
    priced = [s for s in snapshots if s.get("yes_price") is not None]

    if len(priced) < 2:
        return {"velocity_1h": 0.0, "velocity_4h": 0.0, "direction": None, "current_price": None}

    current_price = float(priced[-1]["yes_price"])
    now = datetime.now(timezone.utc)

    def price_at_offset(hours: int) -> float | None:
        cutoff = now - timedelta(hours=hours)
        candidates = [s for s in priced if _parse_ts(s["snapshot_at"]) <= cutoff]
        if candidates:
            return float(candidates[-1]["yes_price"])
        # Fallback: oldest available
        return float(priced[0]["yes_price"])

    price_1h = price_at_offset(1)
    price_4h = price_at_offset(4)

    def pct_change(old: float | None) -> float:
        if old is None or old == 0:
            return 0.0
        return (current_price - old) / old

    velocity_1h = pct_change(price_1h)
    velocity_4h = pct_change(price_4h)

    direction = "UP" if velocity_1h > 0.001 else ("DOWN" if velocity_1h < -0.001 else None)

    return {
        "velocity_1h": round(velocity_1h, 6),
        "velocity_4h": round(velocity_4h, 6),
        "direction": direction,
        "current_price": current_price,
        "price_1h_ago": price_1h,
        "price_4h_ago": price_4h,
    }


def detect_whale_herding_v2(
    snapshots: list,
    market_id: str = "",
    falcon_candidates: dict | None = None,
    pms_whale_summary: dict | None = None,
) -> dict:
    """
    Priority-based herding detection with three sources:

    1. Falcon Market Insights (agent_id=575) — concentration >30% = strongest signal
       Currently broken server-side; gracefully skipped when falcon_candidates is empty.
    2. PMS Agent API (action=whales) — large recent trades as confirmation
    3. Snapshot-based herding (existing detect_whale_herding) — fallback from DB

    Returns same structure as detect_whale_herding():
      {detected, direction, strength, sample_size, source}
    """
    # Source 1: Falcon herding candidates
    if falcon_candidates and market_id in falcon_candidates:
        fc = falcon_candidates[market_id]
        top1_pct = fc.get("top1_wallet_pct", 0)
        # direction from Falcon if available, otherwise treat as undirected
        direction = fc.get("direction")  # YES/NO or None
        strength = min(top1_pct / 100.0, 1.0)
        logger.debug(f"Herding v2 [Falcon]: {market_id[:20]} top1={top1_pct:.0f}% dir={direction}")
        return {
            "detected": True,
            "direction": direction,
            "strength": strength,
            "sample_size": 1,
            "source": "falcon",
        }

    # Source 2: PMS Agent API whale summary
    if pms_whale_summary and market_id in pms_whale_summary:
        s = pms_whale_summary[market_id]
        if s["whale_direction"] in ("YES", "NO"):
            count = s["whale_trade_count"]
            # Strength proxy: more trades = stronger signal, capped at 1.0
            strength = min(count / 5.0, 1.0)
            logger.debug(
                f"Herding v2 [PMS]: {market_id[:20]} dir={s['whale_direction']} "
                f"trades={count} ${s['whale_volume_usd']:,.0f}"
            )
            return {
                "detected": True,
                "direction": s["whale_direction"],
                "strength": strength,
                "sample_size": count,
                "source": "pms_agent",
            }

    # Source 3: Snapshot-based (existing logic, reads whale_direction from DB snapshots)
    result = detect_whale_herding(snapshots)
    result["source"] = "snapshots"
    return result


def analyze_market(market_id: str) -> dict:
    """
    Full divergence analysis for a market.
    Main entry point used by signal_engine.
    """
    snapshots = get_recent_snapshots(market_id, hours=4)

    if len(snapshots) < 3:
        return {"sufficient_data": False, "snapshot_count": len(snapshots)}

    herding = detect_whale_herding(snapshots)
    velocity = detect_price_velocity(snapshots)

    divergence_detected = False
    contrarian_direction = None
    divergence_score = 0.0

    # Herding + velocity aligned in same direction = probable bot overshoot
    if herding["detected"] and velocity["direction"]:
        herding_up = herding["direction"] == "YES"
        velocity_up = velocity["direction"] == "UP"
        aligned = herding_up == velocity_up

        if aligned:
            divergence_detected = True
            contrarian_direction = "NO" if herding_up else "YES"
            # Score: herding strength (60%) + velocity magnitude (40%), capped at 100
            vel_norm = min(abs(velocity["velocity_1h"]) / 0.10, 1.0)  # 10% move = 1.0
            divergence_score = round((herding["strength"] * 0.60 + vel_norm * 0.40) * 100, 2)

    return {
        "sufficient_data": True,
        "snapshot_count": len(snapshots),
        "herding": herding,
        "velocity": velocity,
        "divergence_detected": divergence_detected,
        "contrarian_direction": contrarian_direction,
        "divergence_score": divergence_score,
        "current_price": velocity.get("current_price"),
    }
