"""
Profile Enricher — dual-strategy wallet enrichment.

Computes deep KPIs for a wallet and writes them to `wallet_profiles`. Agnostic
of strategy: a wallet may come from spec_ranking (SPECIALIST), scalper_pool
(SCALPER), or both.

Scope (MVP, per plan):
  - Bloque 0  (control + strategy context)
  - Bloque 1  (universe & market-type coverage)
  - Bloque 3  (exit management — only hold_to_resolution_pct proxy)
  - Bloque 4  (sizing & conviction)
  - Bloque 5  (portfolio — partial)
  - Bloque 6  (temporal activity + momentum)
  - Archetype classification (Hearthstone-style)

Deferred (require endDate cross-reference or market price at entry):
  - Bloque 2  (entry timing)
  - Bloque 3 full (exit quality)
  - Bloque 7  (signal independence)

Designed to be called from the run_profile_enricher daemon one wallet at a
time, or from ad-hoc scripts for targeted enrichment.
"""
from __future__ import annotations

import time
from collections import defaultdict
from statistics import median
from typing import Any, Optional

from src.strategies.common.data_client import DataClient
from src.strategies.specialist.market_type_classifier import classify
from src.strategies.specialist.specialist_profiler import _cv, _is_bot_heuristic
from src.strategies.specialist.universe_config import UNIVERSE_FOR_TYPE
from src.utils.logger import logger

ENRICHMENT_VERSION = 2  # v2: avg_hold_time_minutes, hr_cashpnl_confirmed_pct, SCALPER_BOT archetype
ANALYSIS_WINDOW_DAYS = 120
STALE_AFTER_DAYS = 7


def _usdc(t: dict) -> float:
    """Position size in USDC, with fallback (same pattern as type_context_builder)."""
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


def _safe_ratio(num: float, den: float) -> Optional[float]:
    if den <= 0:
        return None
    return num / den


def _gini(values: list[float]) -> Optional[float]:
    """Gini coefficient for a list of non-negative values (0 = uniform, 1 = one dominates)."""
    n = len(values)
    if n < 2:
        return None
    vals = sorted(v for v in values if v >= 0)
    if not vals:
        return None
    total = sum(vals)
    if total <= 0:
        return None
    cumulative = 0.0
    for i, v in enumerate(vals, start=1):
        cumulative += i * v
    return round((2.0 * cumulative) / (n * total) - (n + 1.0) / n, 4)


class ProfileEnricher:
    """Compute an enriched profile for a single wallet from live Polymarket APIs."""

    def __init__(self, data: DataClient):
        self._data = data

    # ── Public entry point ──────────────────────────────────────────────

    def enrich_wallet(
        self,
        wallet: str,
        *,
        strategies_active: list[str],
        specialist_score: Optional[float] = None,
        scalper_rank: Optional[int] = None,
        scalper_status: Optional[str] = None,
        previous_detected_specialist_at: Optional[int] = None,
        previous_detected_scalper_at: Optional[int] = None,
    ) -> Optional[dict]:
        """Fetch data for one wallet and build its enrichment row.

        Returns a dict ready to upsert into `wallet_profiles`, or None on total
        API failure (the caller should retry later).
        """
        now_ts = int(time.time())
        window_start = now_ts - ANALYSIS_WINDOW_DAYS * 86400

        try:
            trades = self._data.get_all_wallet_trades(wallet, start=window_start)
        except Exception as e:
            logger.warning(f"  enricher: trades fetch failed {wallet[:10]}…: {e}")
            return None

        try:
            positions = self._data.get_wallet_positions(wallet, limit=500)
        except Exception as e:
            logger.debug(f"  enricher: positions fetch failed {wallet[:10]}…: {e}")
            positions = []

        profile: dict[str, Any] = {
            "wallet": wallet,
            "enriched_at": now_ts,
            "enrichment_version": ENRICHMENT_VERSION,
            "analysis_window_days": ANALYSIS_WINDOW_DAYS,
            "stale_after_days": STALE_AFTER_DAYS,
            "trades_analyzed": len(trades),
            "strategies_active": list(strategies_active or []),
            "specialist_score": specialist_score,
            "scalper_rank": scalper_rank,
            "scalper_status": scalper_status,
            "detected_by_specialist_at": (
                previous_detected_specialist_at
                or (now_ts if "SPECIALIST" in strategies_active else None)
            ),
            "detected_by_scalper_at": (
                previous_detected_scalper_at
                or (now_ts if "SCALPER" in strategies_active else None)
            ),
        }

        # Resolve each conditionId's outcome (win/lose/open) using /positions cashPnl
        pos_pnl, pos_open, total_position_value = _resolve_positions(positions)
        profile["positions_analyzed"] = len(pos_pnl)

        # Block 1 — Coverage by universe / market type
        coverage_kpis = _compute_coverage_kpis(trades, pos_pnl, pos_open)
        profile.update(coverage_kpis)

        # Block 3 — Exit management (proxy only in MVP)
        profile["hold_to_resolution_pct"] = _compute_hold_to_resolution(
            trades, pos_pnl, pos_open
        )

        # Block 4 — Sizing & conviction
        sizing_kpis = _compute_sizing_kpis(trades, pos_pnl, pos_open)
        profile.update(sizing_kpis)

        # Block 5 — Portfolio (partial)
        profile.update(_compute_portfolio_kpis(trades, coverage_kpis, total_position_value))

        # Block 6 — Temporal & momentum
        profile.update(_compute_temporal_kpis(trades, pos_pnl, pos_open))

        # v3.0: recent-window actual WR (last 30 days) — used to detect when
        # the aggregate type_hit_rates diverges from recent real performance.
        # We compute this separately from type_hit_rates (which spans 120d).
        profile["last_30d_actual_wr"] = _compute_last_30d_actual_wr(
            trades, pos_pnl, pos_open
        )

        # v3.0: market-maker / negativeRisk arbitrage detection. These wallets
        # (like "ZhangMuZhi.." at +$33k/day) operate through REDEEM+MERGE on
        # multi-outcome markets, not directional bets. Their edge does not
        # transfer to copy-traders — we must exclude them from the pool.
        mm_info = _is_market_maker_heuristic(trades)
        profile["is_market_maker"] = mm_info["is_mm"]
        profile["mm_confidence"] = mm_info["confidence"]
        profile["mm_signals"] = mm_info["signals"]

        # Bot flag is computed from raw trades (heuristic reused from specialist_profiler)
        is_bot = _is_bot_heuristic(trades) if len(trades) >= 20 else False

        # Archetype classification
        archetype_info = _classify_archetype(profile, is_bot=is_bot)
        profile.update(archetype_info)

        # Confidence & completeness
        profile["data_completeness_pct"] = _completeness(profile)
        profile["profile_confidence"] = _confidence_from(profile)

        # Priority score — base for the enricher queue ordering + dashboard sort
        profile["priority_score"] = _priority_score(profile)

        return profile


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions (module-level so they're unit-testable)
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_positions(
    positions: list[dict],
) -> tuple[dict[str, float], set[str], float]:
    """Return (cashPnl-by-cid, open-cids, total_current_value)."""
    pos_pnl: dict[str, float] = {}
    pos_open: set[str] = set()
    total_value = 0.0
    for p in positions or []:
        cid = p.get("conditionId")
        if not cid:
            continue
        cash_pnl = p.get("cashPnl")
        if cash_pnl is None:
            pos_open.add(cid)
        else:
            try:
                pos_pnl[cid] = float(cash_pnl)
            except (TypeError, ValueError):
                pass
        try:
            total_value += float(p.get("currentValue") or p.get("size") or 0)
        except (TypeError, ValueError):
            pass
    return pos_pnl, pos_open, total_value


def _group_trades_by_cid(trades: list[dict]) -> dict[str, list[dict]]:
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        cid = t.get("conditionId")
        if cid:
            by_cid[cid].append(t)
    return dict(by_cid)


def _infer_win(
    cid: str,
    mkt_trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> Optional[bool]:
    """Return True/False for resolved markets, None if open/indeterminate."""
    if cid in pos_open:
        return None
    if cid in pos_pnl:
        return pos_pnl[cid] > 0
    sells = [t for t in mkt_trades if t.get("side") == "SELL"]
    buys = [t for t in mkt_trades if t.get("side") == "BUY"]
    if not sells:
        return None
    return (sum(_usdc(t) for t in sells) - sum(_usdc(t) for t in buys)) > 0


def _pnl_for_cid(
    cid: str,
    mkt_trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> Optional[float]:
    """Estimated USDC P&L for a resolved market. None if open."""
    if cid in pos_open:
        return None
    if cid in pos_pnl:
        return pos_pnl[cid]
    sells = [t for t in mkt_trades if t.get("side") == "SELL"]
    if not sells:
        return None
    buys = [t for t in mkt_trades if t.get("side") == "BUY"]
    return sum(_usdc(t) for t in sells) - sum(_usdc(t) for t in buys)


def _is_market_maker_heuristic(trades: list[dict]) -> dict:
    """Detect negativeRisk arbitrage / market maker wallets from trade data.

    Returns {is_mm, confidence (0..1), signals {...}}.

    Three independent signals — 2/3 triggered → classify as MM.

    1. BUY/SELL skew: MMs exit via REDEEM/MERGE (on-chain), not via SELL.
       A ratio > 50:1 is a very strong signal — legitimate traders close
       positions by selling. We look at the last 180 days.

    2. Price-near-edge concentration: arb bots buy near $0.99 (or near
       $0.01 on the opposite side) on multi-outcome markets where the sum
       of probabilities is miscalibrated. >25% of trades at price ≥ 0.95
       OR ≤ 0.05 is uncommon for directional traders.

    3. Same-event multi-outcome presence: MMs hold positions across many
       outcomes of the same event (e.g. 5 sub-markets of a view-count
       event). >40% of trades concentrated in events where the wallet
       touched ≥3 outcomes signals arbitrage of multi-outcome spreads.
    """
    if len(trades) < 20:
        return {"is_mm": False, "confidence": 0.0, "signals": {}}

    # Signal 1: BUY/SELL ratio
    buys = sum(1 for t in trades if (t.get("side") or "").upper() == "BUY")
    sells = sum(1 for t in trades if (t.get("side") or "").upper() == "SELL")
    total = buys + sells
    if total == 0:
        return {"is_mm": False, "confidence": 0.0, "signals": {}}
    buy_ratio = buys / total if total else 0
    # Trigger when almost all trades are BUY (>98%) — typical MM fingerprint.
    signal_buy_skew = buy_ratio >= 0.98 and total >= 50

    # Signal 2: price near edges (arbitrage hunting)
    edge_trades = 0
    for t in trades:
        try:
            p = float(t.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p >= 0.95 or (0 < p <= 0.05):
            edge_trades += 1
    edge_ratio = edge_trades / len(trades)
    signal_edge_concentration = edge_ratio >= 0.25

    # Signal 3: same-event multi-outcome coverage
    from collections import defaultdict as _dd
    event_outcomes: dict = _dd(set)
    event_trade_count: dict = _dd(int)
    for t in trades:
        ev = t.get("eventSlug") or ""
        if not ev:
            continue
        # outcome can be "Yes"/"No" for binary, or a specific label for
        # multi-outcome events. conditionId is the more granular handle.
        cid = t.get("conditionId") or t.get("asset")
        if cid:
            event_outcomes[ev].add(cid)
        event_trade_count[ev] += 1

    multi_event_trades = sum(
        count for ev, count in event_trade_count.items()
        if len(event_outcomes.get(ev, set())) >= 3
    )
    multi_ratio = multi_event_trades / len(trades) if trades else 0
    signal_multi_outcome = multi_ratio >= 0.40

    signals = {
        "buy_ratio": round(buy_ratio, 4),
        "edge_price_ratio": round(edge_ratio, 4),
        "multi_outcome_ratio": round(multi_ratio, 4),
        "buy_skew": signal_buy_skew,
        "edge_concentration": signal_edge_concentration,
        "multi_outcome_presence": signal_multi_outcome,
        "total_trades_evaluated": len(trades),
    }

    triggered = sum([signal_buy_skew, signal_edge_concentration, signal_multi_outcome])
    is_mm = triggered >= 2
    # Confidence scales with signals; floor at 0.33 per signal so downstream
    # UI can surface borderline cases ("1/3 signals" = suspicious but not MM).
    confidence = round(triggered / 3.0, 3)

    return {"is_mm": is_mm, "confidence": confidence, "signals": signals}


def _compute_last_30d_actual_wr(
    trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> Optional[float]:
    """Last-30d actual win rate over cashPnl-resolved trades only.

    Separate from `type_hit_rates` which averages across 120 days. Used to
    detect when a titular's historical HR is no longer representative of
    current performance (the 57pp gap we saw in v2.1 run).

    Returns None if fewer than 5 resolved trades in the window (not enough
    statistical signal to block anyone).
    """
    import time as _time
    cutoff = int(_time.time()) - 30 * 86400

    by_cid = _group_trades_by_cid(trades)
    wins = 0
    resolved = 0
    for cid, mkt_trades in by_cid.items():
        # Only trades where the most recent action is within 30d
        latest_ts = max(
            int(t.get("timestamp") or t.get("createdAt") or 0) for t in mkt_trades
        )
        if latest_ts < cutoff:
            continue
        # Prefer cashPnl-confirmed outcomes (authoritative). Skip open or
        # indeterminate — we want true WR, not a speculative count.
        if cid in pos_open:
            continue
        if cid not in pos_pnl:
            continue
        resolved += 1
        if pos_pnl[cid] > 0:
            wins += 1

    if resolved < 5:
        return None
    return round(wins / resolved, 4)


def _compute_coverage_kpis(
    trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> dict[str, Any]:
    """Bloque 1 — coverage by universe and market type."""
    by_cid = _group_trades_by_cid(trades)

    # Per-market_type aggregations
    type_trades: dict[str, int] = defaultdict(int)
    type_wins: dict[str, int] = defaultdict(int)
    type_gains: dict[str, float] = defaultdict(float)
    type_losses: dict[str, float] = defaultdict(float)
    type_cashpnl_n: dict[str, int] = defaultdict(int)   # cashPnl-confirmed decisions
    type_hold_minutes: dict[str, list] = defaultdict(list)  # hold duration per market

    for cid, mkt_trades in by_cid.items():
        first = mkt_trades[0]
        mtype = classify(first)

        # Hold time: first BUY → last SELL (measures actual position duration)
        sorted_t = sorted(
            mkt_trades,
            key=lambda t: int(t.get("timestamp") or t.get("createdAt") or 0),
        )
        buys = [t for t in sorted_t if t.get("side") == "BUY"]
        sells = [t for t in sorted_t if t.get("side") == "SELL"]
        if buys and sells:
            first_ts = int(buys[0].get("timestamp") or buys[0].get("createdAt") or 0)
            last_ts = int(sells[-1].get("timestamp") or sells[-1].get("createdAt") or 0)
            if 0 < first_ts < last_ts:
                type_hold_minutes[mtype].append((last_ts - first_ts) / 60.0)

        win = _infer_win(cid, mkt_trades, pos_pnl, pos_open)
        if win is None:
            continue
        type_trades[mtype] += 1
        if win:
            type_wins[mtype] += 1
        if cid in pos_pnl:  # outcome confirmed by /positions cashPnl (authoritative)
            type_cashpnl_n[mtype] += 1

        pnl = _pnl_for_cid(cid, mkt_trades, pos_pnl, pos_open)
        if pnl is None:
            continue
        if pnl >= 0:
            type_gains[mtype] += pnl
        else:
            type_losses[mtype] += abs(pnl)

    type_hit_rates: dict[str, float] = {}
    type_profit_factors: dict[str, float] = {}
    type_trade_counts: dict[str, int] = {}
    for mtype, n in type_trades.items():
        if n <= 0:
            continue
        hr = type_wins[mtype] / n
        type_hit_rates[mtype] = round(hr, 4)
        type_trade_counts[mtype] = n
        losses = type_losses[mtype]
        if losses > 0:
            type_profit_factors[mtype] = round(type_gains[mtype] / losses, 3)
        elif type_gains[mtype] > 0:
            type_profit_factors[mtype] = 9.99  # effectively infinite
        else:
            type_profit_factors[mtype] = 0.0

    # Collapse market_type → universe using static UNIVERSE_FOR_TYPE map.
    # Types outside known universes are skipped for universe-level stats but
    # kept in type-level fields.
    universe_trades: dict[str, int] = defaultdict(int)
    universe_wins: dict[str, int] = defaultdict(int)
    universe_gains: dict[str, float] = defaultdict(float)
    universe_losses: dict[str, float] = defaultdict(float)
    for mtype, n in type_trades.items():
        universe = UNIVERSE_FOR_TYPE.get(mtype)
        if not universe:
            continue
        universe_trades[universe] += n
        universe_wins[universe] += type_wins[mtype]
        universe_gains[universe] += type_gains[mtype]
        universe_losses[universe] += type_losses[mtype]

    universe_hit_rates: dict[str, float] = {}
    universe_profit_factors: dict[str, float] = {}
    universe_trade_counts: dict[str, int] = {}
    for u, n in universe_trades.items():
        if n <= 0:
            continue
        universe_hit_rates[u] = round(universe_wins[u] / n, 4)
        universe_trade_counts[u] = n
        losses = universe_losses[u]
        if losses > 0:
            universe_profit_factors[u] = round(universe_gains[u] / losses, 3)
        elif universe_gains[u] > 0:
            universe_profit_factors[u] = 9.99
        else:
            universe_profit_factors[u] = 0.0

    # Primary universe = highest hit_rate with ≥5 trades
    eligible_universes = [
        (u, hr) for u, hr in universe_hit_rates.items()
        if universe_trade_counts.get(u, 0) >= 5
    ]
    eligible_universes.sort(key=lambda x: x[1], reverse=True)
    primary_universe = eligible_universes[0][0] if eligible_universes else None
    active_universes = [
        u for u, n in universe_trade_counts.items() if n >= 5
    ]

    # Best market type (≥5 trades)
    eligible_types = [
        (t, hr) for t, hr in type_hit_rates.items()
        if type_trade_counts.get(t, 0) >= 5
    ]
    eligible_types.sort(key=lambda x: x[1], reverse=True)
    best_type = eligible_types[0][0] if eligible_types else None
    best_type_hit_rate = eligible_types[0][1] if eligible_types else None
    best_type_profit_factor = (
        type_profit_factors.get(best_type) if best_type else None
    )

    # Domain expertise breadth: types with hit_rate ≥ 0.57 and ≥5 trades
    breadth = sum(
        1 for t, hr in type_hit_rates.items()
        if hr >= 0.57 and type_trade_counts.get(t, 0) >= 5
    )

    # Cross-universe alpha: mean HR in secondary universes − 0.50 baseline
    secondary_hrs = [
        hr for u, hr in universe_hit_rates.items()
        if u != primary_universe and universe_trade_counts.get(u, 0) >= 5
    ]
    if secondary_hrs:
        cross_alpha = round(sum(secondary_hrs) / len(secondary_hrs) - 0.50, 4)
    else:
        cross_alpha = None

    # Domain agnostic score: inverse of std dev of type hit_rates (eligible).
    # 1.0 = perfectly consistent across types, 0.0 = huge variance.
    if len(eligible_types) >= 2:
        vals = [hr for _, hr in eligible_types]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = var ** 0.5
        # Normalize: std of 0.25 ≈ full spread in [0,1] → score ~0
        domain_agnostic = round(max(0.0, 1.0 - std / 0.25), 4)
    else:
        domain_agnostic = None

    # Per-type Sharpe ratio: group resolved PnL by (type, day), compute
    # annualised Sharpe = mean(daily_pnl) / std(daily_pnl) * sqrt(365).
    # Only for types with ≥5 resolved trades spanning ≥3 distinct days.
    type_sharpe_ratios: dict[str, float] = {}
    # Build daily PnL per type from already-resolved per-cid PnLs.
    type_daily_pnl: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for cid, mkt_trades in by_cid.items():
        first = mkt_trades[0]
        mtype = classify(first)
        pnl = _pnl_for_cid(cid, mkt_trades, pos_pnl, pos_open)
        if pnl is None:
            continue
        # Determine the day from the first trade in this market
        ts = int(first.get("timestamp") or 0)
        if ts > 0:
            day = str(ts // 86400)  # integer day bucket
        else:
            continue
        type_daily_pnl[mtype][day] += pnl

    for mtype, daily_map in type_daily_pnl.items():
        if type_trade_counts.get(mtype, 0) < 5:
            continue
        days = list(daily_map.values())
        if len(days) < 3:
            continue
        mean_pnl = sum(days) / len(days)
        var_pnl = sum((d - mean_pnl) ** 2 for d in days) / len(days)
        std_pnl = var_pnl ** 0.5
        if std_pnl > 0:
            sharpe = round((mean_pnl / std_pnl) * (365 ** 0.5), 3)
        else:
            sharpe = round(mean_pnl * (365 ** 0.5), 3) if mean_pnl > 0 else 0.0
        type_sharpe_ratios[mtype] = sharpe

    # Hold time aggregates
    all_holds = [h for holds in type_hold_minutes.values() for h in holds]
    avg_hold_time_minutes = round(sum(all_holds) / len(all_holds), 1) if all_holds else None
    type_avg_hold_minutes = (
        {mtype: round(sum(h) / len(h), 1) for mtype, h in type_hold_minutes.items() if h}
        or None
    )

    # HR data-quality: % of win/loss calls backed by authoritative cashPnl
    total_resolved = sum(type_trades.values())
    total_confirmed = sum(type_cashpnl_n.values())
    hr_cashpnl_confirmed_pct = (
        round(total_confirmed / total_resolved, 4) if total_resolved > 0 else None
    )

    return {
        "primary_universe": primary_universe,
        "active_universes": sorted(active_universes),
        "universe_hit_rates": universe_hit_rates or None,
        "universe_profit_factors": universe_profit_factors or None,
        "universe_trade_counts": universe_trade_counts or None,
        "cross_universe_alpha": cross_alpha,
        "domain_expertise_breadth": breadth,
        "best_market_type": best_type,
        "best_type_hit_rate": round(best_type_hit_rate, 4) if best_type_hit_rate is not None else None,
        "best_type_profit_factor": best_type_profit_factor,
        "type_hit_rates": type_hit_rates or None,
        "type_profit_factors": type_profit_factors or None,
        "type_trade_counts": type_trade_counts or None,
        "type_sharpe_ratios": type_sharpe_ratios or None,
        "domain_agnostic_score": domain_agnostic,
        "avg_hold_time_minutes": avg_hold_time_minutes,
        "type_avg_hold_minutes": type_avg_hold_minutes,
        "hr_cashpnl_confirmed_pct": hr_cashpnl_confirmed_pct,
    }


def _compute_hold_to_resolution(
    trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> Optional[float]:
    """Proxy: fraction of resolved cids that still appear in /positions with
    cashPnl (i.e. the wallet held until resolution rather than fully selling
    out early). Open positions are excluded from both sides."""
    cids_in_trades = {t.get("conditionId") for t in trades if t.get("conditionId")}
    resolved_in_trades = cids_in_trades - pos_open
    if not resolved_in_trades:
        return None
    held = len(resolved_in_trades & set(pos_pnl.keys()))
    return round(held / len(resolved_in_trades), 4)


def _compute_sizing_kpis(
    trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> dict[str, Any]:
    """Bloque 4 — sizing & conviction."""
    # Per-market total BUY size (one "position" = sum of BUYs in that conditionId)
    by_cid = _group_trades_by_cid(trades)
    sizes: list[float] = []
    sizes_winners: list[float] = []
    sizes_losers: list[float] = []

    for cid, mkt_trades in by_cid.items():
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        if not buys:
            continue
        pos_size = sum(_usdc(t) for t in buys)
        if pos_size <= 0:
            continue
        sizes.append(pos_size)

        win = _infer_win(cid, mkt_trades, pos_pnl, pos_open)
        if win is True:
            sizes_winners.append(pos_size)
        elif win is False:
            sizes_losers.append(pos_size)

    if not sizes:
        return {
            "avg_position_size_usd": None,
            "median_position_size_usd": None,
            "position_size_cv": None,
            "size_conviction_ratio": None,
            "max_position_pct_of_portfolio": None,
            "concentration_gini": None,
            "estimated_portfolio_usd": None,
            "typical_n_simultaneous": None,
            "max_simultaneous_positions": None,
            "avg_capital_deployed_pct": None,
        }

    avg_size = sum(sizes) / len(sizes)
    med_size = median(sizes)
    cv = _cv(sizes)
    if sizes_winners and sizes_losers:
        avg_w = sum(sizes_winners) / len(sizes_winners)
        avg_l = sum(sizes_losers) / len(sizes_losers)
        conviction = _safe_ratio(avg_w, avg_l)
    else:
        conviction = None

    # Estimated portfolio: sum of open position values + a rolling estimate.
    # Practical proxy: max simultaneous capital deployed (reconstructed below).
    simult = _reconstruct_simultaneous(trades)
    typical_simult = (
        sum(simult["n_timeline"]) / len(simult["n_timeline"])
        if simult["n_timeline"] else None
    )
    max_simult = max(simult["n_timeline"]) if simult["n_timeline"] else None
    max_capital = max(simult["capital_timeline"]) if simult["capital_timeline"] else None
    est_portfolio = max_capital * 1.1 if max_capital else None  # small buffer for reserve
    max_pos_pct = (
        _safe_ratio(max(sizes), est_portfolio) if est_portfolio and est_portfolio > 0 else None
    )
    avg_deployed = (
        sum(simult["capital_timeline"]) / len(simult["capital_timeline"]) / est_portfolio
        if simult["capital_timeline"] and est_portfolio and est_portfolio > 0
        else None
    )

    return {
        "avg_position_size_usd": round(avg_size, 2),
        "median_position_size_usd": round(med_size, 2),
        "position_size_cv": round(cv, 4) if cv is not None else None,
        "size_conviction_ratio": round(conviction, 3) if conviction is not None else None,
        "max_position_pct_of_portfolio": round(max_pos_pct, 4) if max_pos_pct is not None else None,
        "concentration_gini": _gini(sizes),
        "estimated_portfolio_usd": round(est_portfolio, 2) if est_portfolio is not None else None,
        "typical_n_simultaneous": round(typical_simult, 2) if typical_simult is not None else None,
        "max_simultaneous_positions": max_simult,
        "avg_capital_deployed_pct": round(avg_deployed, 4) if avg_deployed is not None else None,
    }


def _reconstruct_simultaneous(trades: list[dict]) -> dict[str, list]:
    """Walk the trades timeline to estimate `n` simultaneous open positions and
    the capital deployed at each point. Positions are considered "open" between
    the first BUY and the last SELL per conditionId (crude but useful)."""
    by_cid = _group_trades_by_cid(trades)
    events: list[tuple[int, str, float, str]] = []
    # event = (ts, 'open'|'close', size_usd, cid)
    for cid, mkt_trades in by_cid.items():
        sorted_t = sorted(
            mkt_trades,
            key=lambda t: int(t.get("timestamp") or t.get("createdAt") or 0),
        )
        buys = [t for t in sorted_t if t.get("side") == "BUY"]
        sells = [t for t in sorted_t if t.get("side") == "SELL"]
        if not buys:
            continue
        first_buy_ts = int(buys[0].get("timestamp") or buys[0].get("createdAt") or 0)
        total_buy_usd = sum(_usdc(t) for t in buys)
        last_close_ts = (
            int(sells[-1].get("timestamp") or sells[-1].get("createdAt") or 0)
            if sells else 0
        )
        if first_buy_ts > 0:
            events.append((first_buy_ts, "open", total_buy_usd, cid))
        if last_close_ts > 0:
            events.append((last_close_ts, "close", total_buy_usd, cid))

    events.sort()
    open_cids: set[str] = set()
    open_capital = 0.0
    n_timeline: list[int] = []
    capital_timeline: list[float] = []
    for _, kind, size, cid in events:
        if kind == "open":
            open_cids.add(cid)
            open_capital += size
        else:
            if cid in open_cids:
                open_cids.remove(cid)
            open_capital = max(0.0, open_capital - size)
        n_timeline.append(len(open_cids))
        capital_timeline.append(open_capital)
    return {"n_timeline": n_timeline, "capital_timeline": capital_timeline}


def _compute_portfolio_kpis(
    trades: list[dict],
    coverage: dict[str, Any],
    total_position_value: float,
) -> dict[str, Any]:
    """Bloque 5 — portfolio (partial)."""
    universe_counts = coverage.get("universe_trade_counts") or {}
    total = sum(universe_counts.values()) if universe_counts else 0
    universe_alloc: dict[str, float] = {}
    if total > 0:
        for u, n in universe_counts.items():
            universe_alloc[u] = round(n / total, 4)

    # Market diversification: rolling mean of distinct types open.
    # Quick proxy: number of distinct market types with ≥1 trade in the window.
    type_counts = coverage.get("type_trade_counts") or {}
    distinct_types = len(type_counts)
    diversification = min(1.0, distinct_types / 10.0) if distinct_types else None

    # Max drawdown estimate: longest consecutive loss streak * avg loss size.
    # We approximate by scanning the trade sequence by cid outcome.
    by_cid = _group_trades_by_cid(trades)
    losses_in_order: list[float] = []
    ordered = sorted(
        by_cid.items(),
        key=lambda item: min(
            int(t.get("timestamp") or t.get("createdAt") or 0) for t in item[1]
        ) if item[1] else 0,
    )
    current_loss_streak = 0.0
    worst_loss_streak = 0.0
    for _cid, mkt_trades in ordered:
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        sells = [t for t in mkt_trades if t.get("side") == "SELL"]
        if not buys or not sells:
            continue
        pnl = sum(_usdc(t) for t in sells) - sum(_usdc(t) for t in buys)
        if pnl < 0:
            current_loss_streak += abs(pnl)
            worst_loss_streak = max(worst_loss_streak, current_loss_streak)
            losses_in_order.append(pnl)
        else:
            current_loss_streak = 0.0

    max_dd_pct = None
    # Sharpe proxy: (overall_hr − 0.50) / variance of type hit rates.
    type_hit_rates = coverage.get("type_hit_rates") or {}
    if type_hit_rates:
        hrs = list(type_hit_rates.values())
        mean_hr = sum(hrs) / len(hrs)
        if len(hrs) >= 2:
            var = sum((h - mean_hr) ** 2 for h in hrs) / len(hrs)
            std = var ** 0.5
            sharpe = round((mean_hr - 0.50) / std, 3) if std > 0 else None
        else:
            sharpe = None
    else:
        sharpe = None

    return {
        "universe_allocation": universe_alloc or None,
        "market_diversification_score": round(diversification, 4) if diversification is not None else None,
        "drawdown_response": None,            # Deferred
        "win_streak_response": None,          # Deferred
        "avg_portfolio_turnover_days": None,  # Deferred — needs endDate
        "max_drawdown_estimated_pct": max_dd_pct,
        "recovery_speed_score": None,         # Deferred
        "sharpe_proxy": sharpe,
    }


def _compute_temporal_kpis(
    trades: list[dict],
    pos_pnl: dict[str, float],
    pos_open: set[str],
) -> dict[str, Any]:
    """Bloque 6 — temporal patterns + momentum."""
    now_ts = int(time.time())
    cutoff_30d = now_ts - 30 * 86400
    cutoff_60d = now_ts - 60 * 86400
    cutoff_7d = now_ts - 7 * 86400

    hours_count: dict[int, int] = defaultdict(int)
    weekend = 0
    weekday = 0
    timestamps: list[int] = []
    trades_30d = 0
    trades_7d = 0

    for t in trades:
        ts_raw = t.get("timestamp") or t.get("createdAt") or 0
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        timestamps.append(ts)
        import datetime as _dt
        dt = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
        hours_count[dt.hour] += 1
        if dt.weekday() >= 5:  # 5=Sat, 6=Sun
            weekend += 1
        else:
            weekday += 1
        if ts >= cutoff_30d:
            trades_30d += 1
        if ts >= cutoff_7d:
            trades_7d += 1

    preferred_hour = max(hours_count, key=hours_count.get) if hours_count else None
    active_hours = sum(1 for n in hours_count.values() if n >= max(1, len(trades) // 48))
    weekend_ratio = _safe_ratio(weekend, weekday)
    # Activity burst: check intervals between consecutive trades
    burst = None
    if len(timestamps) >= 10:
        timestamps.sort()
        intervals = [
            timestamps[i + 1] - timestamps[i]
            for i in range(len(timestamps) - 1)
            if timestamps[i + 1] > timestamps[i]
        ]
        if intervals:
            short = sum(1 for iv in intervals if iv < 300)  # <5 min between trades
            burst = (short / len(intervals)) > 0.25

    # Historical avg monthly: based on full window
    total_window_days = ANALYSIS_WINDOW_DAYS
    monthly_avg = len(trades) / (total_window_days / 30.0) if total_window_days > 0 else 0
    if monthly_avg > 0:
        momentum = round((trades_30d / monthly_avg) - 1.0, 3)
    else:
        momentum = None

    # Hit rate trends: compare last 30d vs 30-60d ago
    by_cid = _group_trades_by_cid(trades)
    wins_30d = losses_30d = 0
    wins_prev = losses_prev = 0
    for cid, mkt_trades in by_cid.items():
        win = _infer_win(cid, mkt_trades, pos_pnl, pos_open)
        if win is None:
            continue
        latest_ts = max(
            int(t.get("timestamp") or t.get("createdAt") or 0) for t in mkt_trades
        )
        if latest_ts >= cutoff_30d:
            if win:
                wins_30d += 1
            else:
                losses_30d += 1
        elif latest_ts >= cutoff_60d:
            if win:
                wins_prev += 1
            else:
                losses_prev += 1

    hr_30d = _safe_ratio(wins_30d, wins_30d + losses_30d)
    hr_prev = _safe_ratio(wins_prev, wins_prev + losses_prev)

    if hr_30d is not None and hr_prev is not None:
        if hr_30d > hr_prev + 0.05:
            trend = "IMPROVING"
        elif hr_30d < hr_prev - 0.05:
            trend = "DECLINING"
        else:
            trend = "STABLE"
    else:
        trend = None

    # Hit rate variance: rough estimate using 30-day chunks (max 4 chunks)
    chunk_hrs: list[float] = []
    for i in range(4):
        chunk_start = now_ts - (i + 1) * 30 * 86400
        chunk_end = now_ts - i * 30 * 86400
        wins = losses = 0
        for cid, mkt_trades in by_cid.items():
            win = _infer_win(cid, mkt_trades, pos_pnl, pos_open)
            if win is None:
                continue
            latest_ts = max(
                int(t.get("timestamp") or t.get("createdAt") or 0) for t in mkt_trades
            )
            if chunk_start <= latest_ts < chunk_end:
                if win:
                    wins += 1
                else:
                    losses += 1
        if wins + losses >= 3:
            chunk_hrs.append(wins / (wins + losses))

    if len(chunk_hrs) >= 2:
        mean_hr = sum(chunk_hrs) / len(chunk_hrs)
        variance = sum((h - mean_hr) ** 2 for h in chunk_hrs) / len(chunk_hrs)
        hr_variance = round(variance ** 0.5, 4)
        worst_hr = round(min(chunk_hrs), 4)
    else:
        hr_variance = None
        worst_hr = None

    return {
        "preferred_hour_utc": preferred_hour,
        "active_hours_spread": active_hours,
        "weekend_activity_ratio": round(weekend_ratio, 4) if weekend_ratio is not None else None,
        "activity_burst_pattern": burst,
        "last_30d_trades": trades_30d,
        "last_7d_trades": trades_7d,
        "momentum_score": momentum,
        "hit_rate_trend": trend,
        "hit_rate_last_30d": round(hr_30d, 4) if hr_30d is not None else None,
        "hit_rate_variance": hr_variance,
        "worst_30d_hit_rate": worst_hr,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Classification: archetype + rarity + confidence
# ═══════════════════════════════════════════════════════════════════════════

def _classify_archetype(profile: dict, *, is_bot: bool) -> dict[str, Any]:
    """Assign a primary archetype using the priority rules from the plan.
    The rule that matches wins; ties broken by priority order."""
    breadth = profile.get("domain_expertise_breadth") or 0
    best_hr = profile.get("best_type_hit_rate") or 0.0
    best_trades = 0
    if profile.get("best_market_type") and profile.get("type_trade_counts"):
        best_trades = (profile.get("type_trade_counts") or {}).get(
            profile["best_market_type"], 0
        )

    est_portfolio = profile.get("estimated_portfolio_usd") or 0
    max_pos_pct = profile.get("max_position_pct_of_portfolio") or 0
    hold_pct = profile.get("hold_to_resolution_pct") or 0
    last_30d = profile.get("last_30d_trades") or 0
    avg_size = profile.get("avg_position_size_usd") or 0
    trend = profile.get("hit_rate_trend")
    momentum = profile.get("momentum_score") or 0
    type_hrs = profile.get("type_hit_rates") or {}
    type_counts = profile.get("type_trade_counts") or {}

    avg_hold = profile.get("avg_hold_time_minutes")

    archetype = None
    confidence = 0.5

    if is_bot:
        archetype, confidence = "BOT", 0.95
    elif avg_hold is not None and avg_hold < 5:
        # Hold time < 5 minutes = high-frequency scalper. Excluded from copy pools
        # regardless of portfolio size (e.g. whales who scalp intraday on Polymarket).
        archetype, confidence = "SCALPER_BOT", 0.90
    elif est_portfolio > 50_000 or max_pos_pct > 0.25:
        archetype, confidence = "WHALE", 0.80
    # EDGE_HUNTER proxy in MVP: strong HR on types where winner entries are cheap.
    # Full version needs Bloque 2 (avg_entry_price_winners). Keep the slot wired.
    elif hold_pct >= 0.75 and best_hr >= 0.60:
        archetype, confidence = "HODLER", 0.75
    elif breadth <= 2 and best_hr >= 0.62 and best_trades >= 10:
        archetype, confidence = "SPECIALIST", 0.85
    elif breadth >= 4 and _all_above(type_hrs, type_counts, 0.55, 5):
        archetype, confidence = "GENERALIST", 0.80
    elif last_30d > 50 and 0 < avg_size < 200:
        archetype, confidence = "SCALPER_PROFILE", 0.80
    else:
        archetype, confidence = "GENERALIST", 0.50  # default fallback

    # Secondary traits (max 2)
    traits: list[str] = []
    if trend == "IMPROVING" and momentum > 0.2:
        traits.append("HOT")
    elif trend == "DECLINING":
        traits.append("COLD")
    # DISCIPLINED / CONTRARIAN deferred (need Bloque 3 full / Bloque 7)

    # Rarity — requires specialist_score and confidence
    rarity = _classify_rarity(profile)

    return {
        "primary_archetype": archetype,
        "archetype_confidence": round(confidence, 3),
        "archetype_traits": traits[:2],
        "rarity_tier": rarity,
    }


def _all_above(
    type_hrs: dict[str, float],
    type_counts: dict[str, int],
    min_hr: float,
    min_trades: int,
) -> bool:
    """Check that every market type with ≥ min_trades has hr ≥ min_hr."""
    eligible = [
        type_hrs[t] for t, n in type_counts.items()
        if n >= min_trades and t in type_hrs
    ]
    if len(eligible) < 2:
        return False
    return all(hr >= min_hr for hr in eligible)


def _classify_rarity(profile: dict) -> str:
    """Rough rarity using specialist_score (if present) and confidence.
    We don't have global percentiles yet — use static thresholds. A nightly
    re-calibration task could refine these later."""
    score = profile.get("specialist_score") or 0.0
    conf_done = profile.get("profile_confidence")  # may not be set yet
    # If we don't know confidence at this stage (order of calls), treat as None
    # Rarity thresholds are conservative to avoid over-calling LEGENDARIES early.
    if score >= 0.85:
        return "LEGENDARY"
    if score >= 0.70:
        return "EPIC"
    if score >= 0.50:
        return "RARE"
    # Scalper-only wallets (no spec score) → infer from scalper_rank
    rank = profile.get("scalper_rank")
    if rank is not None and isinstance(rank, (int, float)):
        if rank <= 3:
            return "EPIC"
        if rank <= 10:
            return "RARE"
    return "COMMON"


# ═══════════════════════════════════════════════════════════════════════════
# Completeness, confidence, priority
# ═══════════════════════════════════════════════════════════════════════════

# Fields that the MVP is expected to populate when data is sufficient.
_MVP_EXPECTED_FIELDS = [
    # Bloque 1
    "primary_universe", "active_universes", "universe_hit_rates",
    "universe_trade_counts", "best_market_type", "best_type_hit_rate",
    "type_hit_rates", "type_trade_counts", "domain_expertise_breadth",
    # Bloque 3 (proxy)
    "hold_to_resolution_pct",
    # Bloque 4
    "avg_position_size_usd", "median_position_size_usd", "position_size_cv",
    "estimated_portfolio_usd", "typical_n_simultaneous",
    # Bloque 5
    "universe_allocation", "market_diversification_score", "sharpe_proxy",
    # Bloque 6
    "preferred_hour_utc", "last_30d_trades", "last_7d_trades",
    "momentum_score", "hit_rate_trend",
    # Classification
    "primary_archetype", "rarity_tier",
]


def _completeness(profile: dict) -> float:
    filled = sum(1 for f in _MVP_EXPECTED_FIELDS if profile.get(f) is not None)
    return round(filled / len(_MVP_EXPECTED_FIELDS), 4)


def _confidence_from(profile: dict) -> str:
    cmpl = profile.get("data_completeness_pct") or 0
    trades = profile.get("trades_analyzed") or 0
    positions = profile.get("positions_analyzed") or 0
    if cmpl >= 0.80 and trades >= 30 and positions >= 10:
        return "HIGH"
    if cmpl >= 0.60 and trades >= 15:
        return "MEDIUM"
    return "LOW"


def _priority_score(profile: dict) -> float:
    """Base priority for dashboard sorting. The live enricher daemon boosts
    this with per-tick factors (active positions, never-enriched, stale)."""
    base = profile.get("specialist_score") or 0.0
    scalper_rank = profile.get("scalper_rank")
    if scalper_rank and isinstance(scalper_rank, (int, float)) and scalper_rank > 0:
        base = max(base, 1.0 / scalper_rank)
    if profile.get("profile_confidence") == "HIGH":
        base += 0.15
    elif profile.get("profile_confidence") == "MEDIUM":
        base += 0.05
    return round(base, 4)
