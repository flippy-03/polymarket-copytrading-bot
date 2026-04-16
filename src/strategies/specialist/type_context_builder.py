"""
Type context builder — aggregates per-type performance for a wallet.

Given a wallet's trades + positions, returns:
  - all_type_activity: {market_type → TypeActivity}
  - top_types_by_hitrate: up to 3 types (min 5 trades) sorted by hit rate
  - top_types_by_activity: up to 3 types sorted by total trades

Used by specialist_profiler to enrich SpecialistProfile.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from src.strategies.specialist.market_type_classifier import classify


@dataclass
class TypeActivity:
    market_type: str
    trades: int = 0
    wins: int = 0
    total_position_usd: float = 0.0
    last_active_ts: int = 0
    recent_30d_trades: int = 0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def avg_position_usd(self) -> float:
        return self.total_position_usd / self.trades if self.trades > 0 else 0.0


def _usdc(t: dict) -> float:
    try:
        v = t.get("usdcSize")
        if v is not None:
            return float(v)
    except (TypeError, ValueError):
        pass
    try:
        return float(t.get("size") or 0) * float(t.get("price") or 0.5)
    except (TypeError, ValueError):
        return 0.0


def build_context(
    trades: list[dict],
    positions: Optional[list[dict]],
) -> dict[str, TypeActivity]:
    """
    Build per-type activity from a wallet's trades + positions.

    Resolved markets: uses /positions cashPnl as authoritative win/loss signal.
    Open markets: excluded from win/loss (counted for activity only).
    """
    now = time.time()
    cutoff_30d = now - 30 * 86400

    # Map conditionId → cashPnl from /positions (authoritative for wins)
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

    # Group trades by conditionId
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        cid = t.get("conditionId")
        if cid:
            by_cid[cid].append(t)

    activity: dict[str, TypeActivity] = defaultdict(lambda: TypeActivity(market_type=""))

    for cid, mkt_trades in by_cid.items():
        # Use first trade's market metadata for classification
        first = mkt_trades[0]
        mtype = classify(first)

        if activity[mtype].market_type == "":
            activity[mtype].market_type = mtype

        act = activity[mtype]
        act.trades += 1

        # Position size (use latest BUY size)
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        if buys:
            pos_usd = sum(_usdc(t) for t in buys)
            act.total_position_usd += pos_usd

        # Last active timestamp
        for t in mkt_trades:
            ts = t.get("timestamp") or t.get("createdAt") or 0
            try:
                ts_val = int(ts)
                if ts_val > act.last_active_ts:
                    act.last_active_ts = ts_val
            except (TypeError, ValueError):
                pass

        # Recent 30d activity
        latest_ts = act.last_active_ts
        if latest_ts >= cutoff_30d:
            act.recent_30d_trades += 1

        # Win determination (only for resolved markets)
        if cid in pos_open:
            continue  # Open — don't count win/loss
        if cid in pos_pnl:
            if pos_pnl[cid] > 0:
                act.wins += 1
        else:
            # No /positions entry → fully exited via activity
            sells = [t for t in mkt_trades if t.get("side") == "SELL"]
            buys_sum = sum(_usdc(t) for t in buys)
            sells_sum = sum(_usdc(t) for t in sells)
            if sells and (sells_sum - buys_sum) > 0:
                act.wins += 1

    return dict(activity)


def top_types(
    activity: dict[str, TypeActivity],
    by: str = "hit_rate",
    min_trades: int = 5,
    n: int = 3,
) -> list[TypeActivity]:
    """
    Return top N types sorted by 'hit_rate' or 'trades'.
    Only includes types with at least min_trades resolved trades.
    """
    eligible = [a for a in activity.values() if a.trades >= min_trades]
    if by == "hit_rate":
        eligible.sort(key=lambda a: a.hit_rate, reverse=True)
    else:
        eligible.sort(key=lambda a: a.trades, reverse=True)
    return eligible[:n]
