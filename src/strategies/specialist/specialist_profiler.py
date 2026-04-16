"""
Specialist profiler — the core detection pipeline (spec §3-4).

For a given wallet + universe, evaluates whether the wallet qualifies as a
specialist and returns a SpecialistProfile if so.

The 7-step pipeline:
  1. Fetch trades (data_client, 120 days)
  2. Classify each trade by market type (local, 0 requests)
  3. Filter by universe trade count (fast reject, most wallets fail here)
  4. Determine net position per conditionId (local)
  5. Verify resolution via /positions cashPnl (1-3 requests)
  6. Compute hit rate, streak, recency, avg size
  7. Calculate specialist_score; build type context
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from src.strategies.common import config as C
from src.strategies.common.data_client import DataClient
from src.strategies.specialist.market_type_classifier import classify
from src.strategies.specialist.type_context_builder import (
    TypeActivity,
    build_context,
    top_types,
)
from src.utils.logger import logger


@dataclass
class SpecialistProfile:
    address: str
    universe: str

    # Core hit-rate metrics (universe-specific)
    universe_trades: int
    universe_wins: int
    universe_hit_rate: float
    current_streak: int
    last_active_ts: int
    avg_position_usd: float
    is_bot: bool

    # Score
    specialist_score: float

    # Type context
    top_types_by_hitrate: list[TypeActivity] = field(default_factory=list)
    top_types_by_activity: list[TypeActivity] = field(default_factory=list)
    all_type_activity: dict[str, TypeActivity] = field(default_factory=dict)


def _calculate_score(
    hit_rate: float,
    universe_trades: int,
    last_active_ts: int,
    streak: int,
) -> float:
    """
    specialist_score = 50% hit_rate_score + 20% volume_score +
                       15% recency_score + 15% consistency_score.
    """
    # Hit rate: 50% = 0, 80% = 1
    hr_score = min(max((hit_rate - 0.50) / 0.30, 0.0), 1.0)
    # Volume: 10 trades = 0.33, 30+ = 1.0
    vol_score = min(universe_trades / 30, 1.0)
    # Recency: active <7d = ~1.0, >30d = 0
    days_since = (time.time() - last_active_ts) / 86400
    rec_score = max(0.0, 1.0 - days_since / 30)
    # Consistency: streak 0-5
    con_score = min(max(streak, 0) / 5, 1.0)

    return (
        hr_score * 0.50
        + vol_score * 0.20
        + rec_score * 0.15
        + con_score * 0.15
    )


def _cv(values: list[float]) -> float | None:
    """Coefficient of variation for a list of positive floats. Returns None if < 2 values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5 / mean


def _is_bot_heuristic(trades: list[dict]) -> bool:
    """Very lightweight bot check (the full pipeline is in wallet_filter).

    Two independent tests — either one alone is enough to flag:
      1. Size uniformity  — position-sizing bot (fixed-size orders)
      2. Interval uniformity — speed / HFT bot (fires at fixed cadence)

    Threshold: CV < 0.15 means all values are within ~15% of the mean,
    which is abnormally regular for a human trader.
    """
    if len(trades) < 20:
        return False

    # Test 1 — Suspiciously uniform trade sizes
    sizes = [
        float(t.get("usdcSize") or 0) or float(t.get("size") or 0) * float(t.get("price") or 0.5)
        for t in trades
    ]
    sizes = [s for s in sizes if s > 0]
    cv_size = _cv(sizes)
    if cv_size is not None and cv_size < 0.15:
        return True

    # Test 2 — Suspiciously uniform trade intervals (speed / HFT bot)
    timestamps: list[int] = []
    for t in trades:
        ts = t.get("timestamp") or t.get("createdAt") or 0
        try:
            timestamps.append(int(ts))
        except (TypeError, ValueError):
            pass
    timestamps.sort()
    if len(timestamps) >= 20:
        intervals = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
        intervals = [iv for iv in intervals if iv > 0]  # discard same-second duplicates
        cv_interval = _cv(intervals)
        if cv_interval is not None and cv_interval < 0.15:
            return True

    return False


class SpecialistProfiler:
    def __init__(self, data: DataClient):
        self._data = data

    def profile(
        self,
        address: str,
        universe: str,
        target_market_types: list[str],
    ) -> Optional[SpecialistProfile]:
        """
        Run the 7-step detection pipeline for (address, universe).
        Returns SpecialistProfile if the wallet qualifies, None otherwise.
        """
        four_months_ago = int(time.time()) - 120 * 86400

        # Step 1 — Fetch trades
        try:
            trades = self._data.get_all_wallet_trades(address, start=four_months_ago)
        except Exception as e:
            logger.debug(f"  profiler: get_trades {address[:10]}… failed: {e}")
            return None

        # Step 2 — Classify each trade by market type (local)
        universe_trades_raw: list[dict] = [
            t for t in trades
            if classify(t) in target_market_types
        ]

        # Step 3 — Fast reject by universe trade count
        if len(universe_trades_raw) < C.SPEC_MIN_UNIVERSE_TRADES:
            return None

        # Step 5 — Fetch positions for win verification
        try:
            positions = self._data.get_wallet_positions(address, limit=500)
        except Exception as e:
            logger.debug(f"  profiler: positions {address[:10]}… failed: {e}")
            positions = None

        # Step 4 + 6 — Group by conditionId, compute wins/losses
        pos_pnl: dict[str, float] = {}
        pos_open: set[str] = set()
        for p in positions or []:
            cid = p.get("conditionId")
            if not cid:
                continue
            cash_pnl = p.get("cashPnl")
            if cash_pnl is None:
                pos_open.add(cid)
            else:
                pos_pnl[cid] = float(cash_pnl)

        by_cid: dict[str, list[dict]] = defaultdict(list)
        for t in universe_trades_raw:
            cid = t.get("conditionId")
            if cid:
                by_cid[cid].append(t)

        wins = 0
        losses = 0
        total_pos_usd = 0.0
        last_ts = 0
        streak = 0
        streak_running = 0
        outcome_list: list[bool] = []

        for cid, mkt_trades in by_cid.items():
            if cid in pos_open:
                continue  # Skip open positions

            buys = [t for t in mkt_trades if t.get("side") == "BUY"]
            buy_usd = sum(
                float(t.get("usdcSize") or 0) or float(t.get("size") or 0) * float(t.get("price") or 0.5)
                for t in buys
            )
            total_pos_usd += buy_usd

            # Latest timestamp for this market
            for t in mkt_trades:
                ts = t.get("timestamp") or t.get("createdAt") or 0
                try:
                    ts_val = int(ts)
                    if ts_val > last_ts:
                        last_ts = ts_val
                except (TypeError, ValueError):
                    pass

            # Win determination
            if cid in pos_pnl:
                is_win = pos_pnl[cid] > 0
            else:
                sells = [t for t in mkt_trades if t.get("side") == "SELL"]
                buy_sum = buy_usd
                sell_sum = sum(
                    float(t.get("usdcSize") or 0) or float(t.get("size") or 0) * float(t.get("price") or 0.5)
                    for t in sells
                )
                if not sells:
                    continue  # Can't determine outcome
                is_win = (sell_sum - buy_sum) > 0

            if is_win:
                wins += 1
            else:
                losses += 1
            outcome_list.append(is_win)

        resolved = wins + losses
        if resolved < C.SPEC_MIN_UNIVERSE_TRADES:
            return None

        hit_rate = wins / resolved

        if hit_rate < C.SPEC_MIN_HIT_RATE:
            return None

        # Streak: count consecutive wins from the end
        for outcome in reversed(outcome_list):
            if outcome:
                streak += 1
            else:
                break

        # Recency check
        days_inactive = (time.time() - last_ts) / 86400 if last_ts > 0 else 999
        if days_inactive > C.SPEC_MAX_INACTIVE_DAYS:
            return None

        avg_pos = total_pos_usd / resolved if resolved > 0 else 0.0

        # Step 7 — Score + type context
        score = _calculate_score(hit_rate, resolved, last_ts, streak)
        if score < C.SPEC_MIN_SCORE:
            return None

        is_bot = _is_bot_heuristic(trades)
        if is_bot:
            return None

        all_type_act = build_context(trades, positions)
        top_hr = top_types(all_type_act, by="hit_rate", min_trades=5, n=3)
        top_vol = top_types(all_type_act, by="trades", min_trades=1, n=3)

        return SpecialistProfile(
            address=address,
            universe=universe,
            universe_trades=resolved,
            universe_wins=wins,
            universe_hit_rate=hit_rate,
            current_streak=streak,
            last_active_ts=last_ts,
            avg_position_usd=avg_pos,
            is_bot=is_bot,
            specialist_score=score,
            top_types_by_hitrate=top_hr,
            top_types_by_activity=top_vol,
            all_type_activity=all_type_act,
        )
