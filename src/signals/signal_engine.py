"""
Signal Engine — main cycle for Phase 2.

For each active market with sufficient snapshot history:
  1. Run divergence analysis (whale herding + price velocity)
  2. Run momentum filter (pattern classification)
  3. Compute smart wallet score
  4. If total_score ≥ SIGNAL_THRESHOLD → insert signal into DB
  5. Expire signals older than 24h
"""

from datetime import datetime, timezone, timedelta
from math import log1p

from collections import defaultdict

import httpx
from collections import defaultdict as _defaultdict_whale

from src.db import supabase_client as db
from src.data.falcon_client import fetch_herding_candidates
from src.signals.divergence_detector import detect_whale_herding_v2, detect_price_velocity
from src.signals.momentum_filter import calculate_momentum_score
from src.signals.contrarian_logic import (
    get_smart_wallet_score,
    should_generate_signal,
)
from src.utils.logger import logger
from src.utils.config import SIGNAL_THRESHOLD, DIVERGENCE_THRESHOLD_MIN, SPORTS_QUESTION_KEYWORDS, MIN_ENTRY_PRICE, MIN_CONTRARIAN_PRICE

_CANDIDATE_TOP_N = 500
_MIN_VOLUME = 1_000
_PMS_AGENT_API_URL = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api"


def _fetch_pms_whale_summary() -> dict[str, dict]:
    """
    Fetch recent whale trades from PMS Agent API and aggregate by market_id.
    Returns {market_id: {whale_direction: YES|NO|MIXED, whale_trade_count: int, whale_volume_usd: float}}
    Filters out sports markets by slug keywords.
    """
    try:
        r = httpx.get(
            _PMS_AGENT_API_URL,
            params={"action": "whales", "limit": 50, "agent_id": "contrarian-bot"},
            timeout=10.0,
        )
        r.raise_for_status()
        body = r.json()
        trades = body.get("data", []) if body.get("ok") else []
    except Exception as e:
        logger.warning(f"PMS whale fetch failed: {e}")
        return {}

    from src.utils.config import SPORTS_QUESTION_KEYWORDS
    by_market: dict = _defaultdict_whale(list)
    for t in trades:
        mid = t.get("market_id") or ""
        if not mid:
            continue
        # Skip sports trades to avoid polluting herding signals
        slug = (t.get("market_slug") or "").lower()
        title = (t.get("market_title") or "").lower()
        if any(kw in title or kw in slug for kw in SPORTS_QUESTION_KEYWORDS):
            continue
        by_market[mid].append(t)

    summary: dict[str, dict] = {}
    for mid, market_trades in by_market.items():
        sides = []
        for t in market_trades:
            side = (t.get("side") or "").upper()
            if side == "BUY":
                sides.append("YES")
            elif side == "SELL":
                sides.append("NO")
        if not sides:
            continue
        yes_count = sides.count("YES")
        no_count = sides.count("NO")
        total = len(sides)
        if yes_count / total >= 0.80:
            direction = "YES"
        elif no_count / total >= 0.80:
            direction = "NO"
        else:
            direction = "MIXED"
        vol = sum(float(t.get("amount_usd") or 0) for t in market_trades)
        summary[mid] = {
            "whale_direction": direction,
            "whale_trade_count": total,
            "whale_volume_usd": vol,
        }

    non_mixed = sum(1 for s in summary.values() if s["whale_direction"] != "MIXED")
    logger.info(f"PMS whales: {len(trades)} trades → {len(summary)} markets ({non_mixed} directional)")
    return summary


def _get_candidate_markets() -> list:
    """
    Select top 500 markets by composite score:
      selection_score = volume_normalized*0.3 + proximity_to_resolution*0.4 + recent_velocity*0.3

    - volume_normalized  : log-scaled relative volume (avoids large markets dominating)
    - proximity_to_resolution: markets closing in 6-72h score highest
    - recent_velocity    : markets already moving in the last 2h score higher
    """
    client = db.get_client()
    now = datetime.now(timezone.utc)

    # Fetch all active unresolved markets with volume >= $1k (paginated)
    all_markets: list[dict] = []
    offset = 0
    while True:
        batch = (
            client.table("markets")
            .select("id,question,volume_24h,yes_price,no_price,end_date")
            .eq("is_active", True)
            .is_("resolution", "null")
            .gte("volume_24h", _MIN_VOLUME)
            .range(offset, offset + 999)
            .execute()
            .data
        )
        all_markets.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    # Filter sports markets already in DB (category field is unreliable from API, use keywords)
    before = len(all_markets)
    all_markets = [
        m for m in all_markets
        if not any(kw in (m.get("question") or "").lower() for kw in SPORTS_QUESTION_KEYWORDS)
    ]
    filtered_sports = before - len(all_markets)

    if not all_markets:
        return []

    logger.info(
        f"Candidate pool: {len(all_markets)} markets with vol>=${_MIN_VOLUME:,} "
        f"(filtered {filtered_sports} sports)"
    )

    # Bulk-fetch last 2h snapshots to compute recent velocity per market
    cutoff_2h = (now - timedelta(hours=2)).isoformat()
    snaps_raw: list[dict] = []
    snap_offset = 0
    while True:
        batch = (
            client.table("market_snapshots")
            .select("market_id,snapshot_at,yes_price")
            .gte("snapshot_at", cutoff_2h)
            .order("snapshot_at", desc=False)
            .range(snap_offset, snap_offset + 999)
            .execute()
            .data
        )
        snaps_raw.extend(batch)
        if len(batch) < 1000:
            break
        snap_offset += 1000

    # Compute |price_change_2h| per market
    snaps_by_market: dict[str, list[float]] = defaultdict(list)
    for s in snaps_raw:
        if s.get("yes_price") is not None:
            snaps_by_market[s["market_id"]].append(float(s["yes_price"]))

    velocity_by_market: dict[str, float] = {}
    for mid, prices in snaps_by_market.items():
        if len(prices) >= 2 and prices[0] > 0:
            velocity_by_market[mid] = abs(prices[-1] - prices[0]) / prices[0]

    # Normalisation denominators
    max_volume = max((float(m.get("volume_24h") or 0) for m in all_markets), default=1.0) or 1.0
    max_velocity = max(velocity_by_market.values(), default=1.0) or 1.0

    scored: list[tuple[float, dict]] = []
    for m in all_markets:
        vol = float(m.get("volume_24h") or 0)
        vol_score = log1p(vol) / log1p(max_volume)

        # Proximity: 1.0 at <=6h, linearly decays to 0.0 at 72h, 0 beyond
        prox_score = 0.0
        end_date = m.get("end_date")
        if end_date:
            try:
                end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                hours_left = (end - now).total_seconds() / 3600
                if hours_left <= 6:
                    prox_score = 1.0
                elif hours_left <= 72:
                    prox_score = 1.0 - (hours_left - 6) / 66
                # > 72h → 0.0
            except Exception:
                pass

        vel = velocity_by_market.get(m["id"], 0.0)
        vel_score = min(vel / max_velocity, 1.0)

        selection_score = vol_score * 0.3 + prox_score * 0.4 + vel_score * 0.3
        scored.append((selection_score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [m for _, m in scored[:_CANDIDATE_TOP_N]]
    logger.info(
        f"Selected top {len(selected)} markets by composite score "
        f"(vol*0.3 + proximity*0.4 + velocity*0.3)"
    )
    return selected


def _fetch_all_snapshots_bulk(market_ids: list) -> dict:
    """
    Pre-fetch last 4h of snapshots for all markets.
    Batches the .in_() filter in chunks of 200 to stay within URL limits.
    Returns {market_id: [snapshots...]} grouped in Python.
    """
    client = db.get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()

    grouped: dict = defaultdict(list)
    batch_size = 200
    for i in range(0, len(market_ids), batch_size):
        chunk = market_ids[i : i + batch_size]
        result = (
            client.table("market_snapshots")
            .select("market_id,snapshot_at,yes_price,no_price,whale_direction,whale_trade_count,whale_volume_usd")
            .in_("market_id", chunk)
            .gte("snapshot_at", cutoff)
            .order("snapshot_at", desc=False)
            .execute()
        )
        for row in result.data:
            grouped[row["market_id"]].append(row)
    return grouped


def _fetch_active_signal_market_ids() -> set:
    """Return set of market_ids that already have an ACTIVE signal."""
    client = db.get_client()
    result = client.table("signals").select("market_id").eq("status", "ACTIVE").execute()
    return {r["market_id"] for r in result.data}


def _expire_old_signals():
    client = db.get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        client.table("signals").update({"status": "EXPIRED"}).eq("status", "ACTIVE").lt("created_at", cutoff).execute()
    except Exception as e:
        logger.warning(f"expire_old_signals failed: {e}")


def run_signal_engine() -> int:
    """
    Main engine cycle. Returns number of new signals generated.
    Uses bulk pre-fetching to avoid N+1 queries.
    """
    markets = _get_candidate_markets()
    if not markets:
        logger.warning("No candidate markets in DB")
        return 0

    _expire_old_signals()

    # Fetch fresh whale data once per cycle (before the market loop)
    falcon_candidates: dict = {}
    try:
        falcon_candidates = fetch_herding_candidates()
    except Exception as e:
        logger.warning(f"Falcon fetch failed: {e}")

    pms_whale_summary: dict = {}
    try:
        pms_whale_summary = _fetch_pms_whale_summary()
    except Exception as e:
        logger.warning(f"PMS whale summary failed: {e}")

    market_ids = [m["id"] for m in markets]

    # Bulk fetch: snapshots and active signals in 2 queries total
    snapshots_by_market = _fetch_all_snapshots_bulk(market_ids)
    active_signal_market_ids = _fetch_active_signal_market_ids()

    client = db.get_client()
    sw_score = get_smart_wallet_score(client)

    generated = 0
    skipped_no_data = 0
    skipped_no_divergence = 0
    skipped_score = 0

    for market in markets:
        market_id = market["id"]
        question = (market.get("question") or "")[:60]

        try:
            if market_id in active_signal_market_ids:
                continue

            snapshots = snapshots_by_market.get(market_id, [])

            # Inline divergence analysis (no extra DB calls)
            if len(snapshots) < 3:
                skipped_no_data += 1
                continue

            herding = detect_whale_herding_v2(
                snapshots,
                market_id=market_id,
                falcon_candidates=falcon_candidates,
                pms_whale_summary=pms_whale_summary,
            )
            velocity = detect_price_velocity(snapshots)

            divergence_detected = False
            contrarian_direction = None
            divergence_score = 0.0

            if herding["detected"] and velocity["direction"]:
                herding_up = herding["direction"] == "YES"
                velocity_up = velocity["direction"] == "UP"
                if herding_up == velocity_up:
                    divergence_detected = True
                    contrarian_direction = "NO" if herding_up else "YES"
                    vel_norm = min(abs(velocity["velocity_1h"]) / 0.10, 1.0)
                    divergence_score = round((herding["strength"] * 0.60 + vel_norm * 0.40) * 100, 2)

            # Fallback: velocity-only when no whale data has been collected yet.
            # 5% in 1h is already unusual for event markets (politics, macro, tech).
            elif (
                herding["sample_size"] == 0
                and velocity["direction"]
                and abs(velocity["velocity_1h"]) >= 0.05
            ):
                divergence_detected = True
                contrarian_direction = "NO" if velocity["direction"] == "UP" else "YES"
                vel_norm = min(abs(velocity["velocity_1h"]) / 0.05, 1.0)
                divergence_score = round(vel_norm * 100, 2)

            if not divergence_detected:
                skipped_no_divergence += 1
                continue

            # Step 2: Momentum score
            mom = calculate_momentum_score(velocity["velocity_1h"], velocity["velocity_4h"])

            # Step 3: Final decision
            trade, total_score = should_generate_signal(
                divergence_score=divergence_score,
                momentum_score=mom["score"],
                smart_wallet_score=sw_score,
                momentum_tradeable=mom["tradeable"],
                divergence_detected=divergence_detected,
            )

            if not trade:
                skipped_score += 1
                continue

            # Step 4: Build and save signal
            direction = contrarian_direction
            price = velocity.get("current_price")

            # FIX: price is required — skip if unavailable (no price = no filters = bad signal)
            if price is None:
                logger.debug(f"Skip {question[:40]}: no current price available")
                skipped_no_data += 1
                continue

            # Skip markets near resolution — bad risk/reward in both directions:
            #   YES signal: yes_price > 0.95 → market almost certainly resolves YES, no edge
            #   NO signal:  yes_price < 0.05 → market almost certainly resolves NO, no edge
            if direction == "YES" and price > (1 - MIN_ENTRY_PRICE):
                logger.debug(f"Skip {question[:40]}: YES near resolution (yes={price:.3f})")
                skipped_score += 1
                continue
            if direction == "NO" and price < MIN_ENTRY_PRICE:
                logger.debug(f"Skip {question[:40]}: NO near resolution (yes={price:.3f})")
                skipped_score += 1
                continue

            entry = price if direction == "YES" else round(1 - price, 4)

            if entry < MIN_ENTRY_PRICE:
                logger.debug(f"Skip {question[:40]}: entry price {entry:.3f} < MIN_ENTRY_PRICE")
                skipped_score += 1
                continue

            # Contrarian price floor: don't fade a market already 80%+ resolved in the
            # opposite direction — rational price discovery, not manipulation.
            # Symmetric: YES entry >= 0.20, NO entry >= 0.20 (i.e. yes_price <= 0.80).
            if entry < MIN_CONTRARIAN_PRICE:
                logger.debug(f"Skip {question[:40]}: entry {entry:.3f} < MIN_CONTRARIAN_PRICE — market near resolution")
                skipped_score += 1
                continue

            # Contrarian price ceiling: if NO entry > 0.80, take-profit (entry × 1.50)
            # would exceed 1.0 — mathematically unreachable in a binary market.
            # Symmetric cap: entry must be in [MIN_CONTRARIAN_PRICE, 1 - MIN_CONTRARIAN_PRICE].
            if entry > (1 - MIN_CONTRARIAN_PRICE):
                logger.debug(f"Skip {question[:40]}: entry {entry:.3f} > {1 - MIN_CONTRARIAN_PRICE:.2f} — TP unreachable in binary market")
                skipped_score += 1
                continue
            now = datetime.now(timezone.utc).isoformat()
            expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

            signal = {
                "market_id": market_id,
                "signal_type": "CONTRARIAN_LONG" if direction == "YES" else "CONTRARIAN_SHORT",
                "direction": direction,
                "confidence": round(total_score / 100, 4),
                "price_at_signal": price,
                "divergence_at_signal": velocity["velocity_1h"],
                "volume_at_signal": market.get("volume_24h"),
                "divergence_score": divergence_score,
                "momentum_score": mom["score"],
                "smart_wallet_score": sw_score,
                "total_score": total_score,
                "status": "ACTIVE",
                "created_at": now,
                "expires_at": expires,
            }

            db.insert("signals", signal)
            generated += 1

            logger.info(
                f"🎯 SIGNAL [{direction}] score={total_score:.1f} | "
                f"pattern={mom['pattern']} | price={price} | {question}"
            )

        except Exception as e:
            logger.warning(f"Signal engine error for {market_id}: {e}")

    logger.info(
        f"Cycle done — {generated} signals | "
        f"no_data={skipped_no_data} no_div={skipped_no_divergence} low_score={skipped_score}"
    )
    return generated
