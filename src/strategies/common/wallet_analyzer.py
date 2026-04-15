"""
Wallet analyzer — derives WalletMetrics from a list of raw trades.

Used by both strategies. Input: trades from DataClient.get_all_wallet_trades().
Output: WalletMetrics dataclass with all fields required by wallet_filter and ranking.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np


@dataclass
class WalletMetrics:
    address: str

    # Tier 1
    total_trades: int = 0
    win_rate: float = 0.0
    track_record_days: int = 0
    avg_holding_period_hours: float = 0.0
    pnl_30d: float = 0.0
    pnl_7d: float = 0.0
    trades_per_month: float = 0.0

    # Tier 2
    profit_factor: float = 0.0
    edge_vs_odds: float = 0.0
    unique_categories: int = 0
    positive_weeks_pct: float = 0.0
    avg_position_size: float = 0.0
    entry_timing_score: float = 0.0

    # Bot detection (intra-wallet signals; cross-wallet tests live in bot_detector)
    interval_cv: float = 0.0
    size_cv: float = 0.0
    max_corr_delay: float = 0.0
    unique_markets_pct: float = 1.0
    is_likely_bot: bool = False

    # Metadata
    categories: list[str] = field(default_factory=list)
    first_trade_ts: int = 0
    last_trade_ts: int = 0
    total_pnl: float = 0.0


_CATEGORY_KEYWORDS = {
    "crypto": ["btc", "bitcoin", "eth", "ethereum", "sol", "solana",
               "crypto", "token", "defi", "memecoin"],
    "politics": ["election", "president", "trump", "biden", "vote",
                 "congress", "senate", "governor", "political"],
    "economics": ["fed", "rate", "inflation", "gdp", "recession",
                  "cpi", "unemployment", "treasury"],
    "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football",
               "game", "match", "championship"],
    "tech": ["ai", "openai", "google", "apple", "microsoft", "tech",
             "spacex", "tesla"],
}


def _usdc(t):
    try:
        v = t.get("usdcSize")
        if v is not None:
            return float(v)
    except (TypeError, ValueError):
        pass
    # Fallback: size * price (used by market /trades endpoint)
    try:
        return float(t.get("size") or 0) * float(t.get("price") or 0.5)
    except (TypeError, ValueError):
        return 0.0


def analyze_wallet(
    trades: list[dict],
    address: str,
    positions: list[dict] | None = None,
) -> WalletMetrics:
    """
    Derive WalletMetrics from activity trades and (optionally) current positions.

    PnL source-of-truth hierarchy:
      1. For markets present in `positions`: use `cashPnl` directly.
         This captures hold-to-resolution correctly (markets that auto-redeemed
         with no explicit SELL row but with a final outcome).
      2. For markets only in `trades` (user fully sold out): compute net from
         activity buy/sell flow.

    Passing `positions=None` falls back to activity-only analysis — biased for
    hold-to-resolution wallets but kept for non-builder callers that don't have
    a DataClient handy.
    """
    m = WalletMetrics(address=address)
    if not trades and not positions:
        return m

    m.total_trades = len(trades)
    timestamps = sorted(int(t.get("timestamp") or 0) for t in trades)
    if timestamps:
        m.first_trade_ts = timestamps[0]
        m.last_trade_ts = timestamps[-1]
        m.track_record_days = max((m.last_trade_ts - m.first_trade_ts) // 86400, 0)

    if m.track_record_days > 0:
        m.trades_per_month = m.total_trades / (m.track_record_days / 30)

    # ── Category detection (heuristic on slug/title) ─────
    # Positions also carry `title`/`slug`, so mix both sources to avoid
    # undercounting categories when a wallet holds-to-resolution.
    found_cats: set[str] = set()
    def _collect_cats(rows):
        for r in rows or []:
            title = (r.get("title") or "").lower()
            slug = (r.get("slug") or "").lower()
            combined = f"{title} {slug}"
            for cat, kws in _CATEGORY_KEYWORDS.items():
                if any(kw in combined for kw in kws):
                    found_cats.add(cat)
    _collect_cats(trades)
    _collect_cats(positions)
    m.categories = sorted(found_cats)
    m.unique_categories = len(found_cats)

    # ── Build per-market view, merging positions + activity ──
    pos_by_cid: dict[str, dict] = {}
    for p in positions or []:
        cid = p.get("conditionId")
        if cid:
            pos_by_cid[cid] = p

    by_market: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_market[t.get("conditionId") or "unknown"].append(t)

    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    ts_30d = now_ts - 30 * 86400
    ts_7d = now_ts - 7 * 86400

    wins = losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    pnl_30d = 0.0
    pnl_7d = 0.0
    total_pnl = 0.0
    holding_periods: list[float] = []
    entry_prices: list[float] = []

    # --- A. Markets present in /positions (authoritative PnL) --------
    for cid, pos in pos_by_cid.items():
        try:
            cash_pnl = float(pos.get("cashPnl") or 0)
        except (TypeError, ValueError):
            cash_pnl = 0.0
        total_pnl += cash_pnl
        if cash_pnl > 0:
            wins += 1
            gross_profit += cash_pnl
        elif cash_pnl < 0:
            losses += 1
            gross_loss += abs(cash_pnl)

        # Holding period / entry price / activity-window flow still use trades.
        mkt_trades = by_market.get(cid, [])
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        sells = [t for t in mkt_trades if t.get("side") == "SELL"]
        for t in mkt_trades:
            ts = int(t.get("timestamp") or 0)
            usdc = _usdc(t)
            if ts >= ts_30d:
                pnl_30d += usdc if t.get("side") == "SELL" else -usdc
            if ts >= ts_7d:
                pnl_7d += usdc if t.get("side") == "SELL" else -usdc
        if buys and sells:
            first_buy = min(int(t.get("timestamp") or 0) for t in buys)
            last_sell = max(int(t.get("timestamp") or 0) for t in sells)
            hp_hours = (last_sell - first_buy) / 3600
            if hp_hours > 0:
                holding_periods.append(hp_hours)
        for t in buys:
            try:
                entry_prices.append(float(t.get("price") or 0.5))
            except (TypeError, ValueError):
                pass

    # --- B. Markets only in /activity (fully exited, not in positions) ---
    for cid, mkt_trades in by_market.items():
        if cid in pos_by_cid:
            continue
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        sells = [t for t in mkt_trades if t.get("side") == "SELL"]

        # With /positions as primary source, a market only appearing in activity
        # is one the wallet fully cashed out of. If there are no sells either,
        # fall back to net=buys*-1 only when positions were never available
        # (legacy path). When positions=None, keep pre-fix behavior (skip).
        if not sells:
            if positions is not None:
                # Fully bought, nothing in positions → edge case (dusted/transferred).
                # Skip silently rather than counting as a loss of unknown size.
                continue
            # Legacy path (no positions provided): preserve old behavior.
            continue
        net = sum(_usdc(t) for t in sells) - sum(_usdc(t) for t in buys)
        total_pnl += net
        if net > 0:
            wins += 1
            gross_profit += net
        elif net < 0:
            losses += 1
            gross_loss += abs(net)

        for t in mkt_trades:
            ts = int(t.get("timestamp") or 0)
            usdc = _usdc(t)
            if ts >= ts_30d:
                pnl_30d += usdc if t.get("side") == "SELL" else -usdc
            if ts >= ts_7d:
                pnl_7d += usdc if t.get("side") == "SELL" else -usdc
        if buys and sells:
            first_buy = min(int(t.get("timestamp") or 0) for t in buys)
            last_sell = max(int(t.get("timestamp") or 0) for t in sells)
            hp_hours = (last_sell - first_buy) / 3600
            if hp_hours > 0:
                holding_periods.append(hp_hours)
        for t in buys:
            try:
                entry_prices.append(float(t.get("price") or 0.5))
            except (TypeError, ValueError):
                pass

    total_markets = wins + losses
    m.win_rate = wins / total_markets if total_markets > 0 else 0.0
    m.pnl_30d = pnl_30d
    m.pnl_7d = pnl_7d
    m.total_pnl = total_pnl
    m.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    m.avg_holding_period_hours = float(np.mean(holding_periods)) if holding_periods else 0.0

    if entry_prices:
        m.edge_vs_odds = m.win_rate - float(np.mean(entry_prices))

    # ── Position sizing ──────────────────────────────────
    sizes = [_usdc(t) for t in trades if t.get("side") == "BUY" and _usdc(t) > 0]
    if sizes:
        m.avg_position_size = float(np.mean(sizes))
        mean = float(np.mean(sizes))
        m.size_cv = float(np.std(sizes) / mean) if mean > 0 else 0.0

    # ── Weekly consistency ───────────────────────────────
    weekly: Counter = Counter()
    for t in trades:
        ts = int(t.get("timestamp") or 0)
        if ts == 0:
            continue
        week = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()[:2]
        usdc = _usdc(t)
        weekly[week] += usdc if t.get("side") == "SELL" else -usdc
    if weekly:
        positive = sum(1 for v in weekly.values() if v > 0)
        m.positive_weeks_pct = positive / len(weekly)

    # ── Intervals between trades (bot test 1) ────────────
    if len(timestamps) > 1:
        intervals = np.diff(timestamps).astype(float)
        mean = float(np.mean(intervals))
        if mean > 0:
            m.interval_cv = float(np.std(intervals) / mean)

    return m
