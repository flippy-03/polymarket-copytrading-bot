"""
Wallet filter pipeline — Tier 1 → Tier 3 (alerts) → Tier 2 → Bot detection.
Shared by both strategies.
"""
from src.strategies.common import config as C
from src.strategies.common.wallet_analyzer import WalletMetrics


def passes_tier1(m: WalletMetrics) -> tuple[bool, str]:
    if m.total_trades < C.MIN_TRADES_TOTAL:
        return False, f"trades={m.total_trades} < {C.MIN_TRADES_TOTAL}"
    # All-time PnL sanity check — rejects wallets with net-negative history.
    # Uses /positions cashPnl as source of truth (not the biased by-market
    # reconstruction from activity that ignored hold-to-resolution markets).
    if m.total_pnl < C.MIN_TOTAL_PNL_USD:
        return False, f"total_pnl=${m.total_pnl:.0f} < ${C.MIN_TOTAL_PNL_USD:.0f}"
    if m.win_rate < C.MIN_WIN_RATE:
        return False, f"win_rate={m.win_rate:.2%} < {C.MIN_WIN_RATE:.0%}"
    if m.track_record_days < C.MIN_TRACK_RECORD_DAYS:
        return False, f"track_record={m.track_record_days}d < {C.MIN_TRACK_RECORD_DAYS}d"
    if m.avg_holding_period_hours > C.MAX_HOLDING_PERIOD_DAYS * 24:
        return False, f"holding={m.avg_holding_period_hours:.0f}h > {C.MAX_HOLDING_PERIOD_DAYS*24}h"
    if C.REQUIRE_POSITIVE_PNL_30D and m.pnl_30d < C.PNL_30D_TOLERANCE:
        return False, f"pnl_30d=${m.pnl_30d:.2f} < {C.PNL_30D_TOLERANCE}"
    if C.REQUIRE_NONNEGATIVE_PNL_7D and m.pnl_7d < 0:
        return False, f"pnl_7d=${m.pnl_7d:.2f} < 0"
    if m.trades_per_month < C.MIN_TRADES_PER_MONTH:
        return False, f"freq={m.trades_per_month:.1f}/mo < {C.MIN_TRADES_PER_MONTH}"
    return True, "OK"


def count_tier2_passes(m: WalletMetrics) -> tuple[int, list[str]]:
    results: list[str] = []
    passed = 0

    ok = m.profit_factor >= C.MIN_PROFIT_FACTOR
    results.append(f"profit_factor={m.profit_factor:.2f} {'ok' if ok else 'fail'}")
    passed += int(ok)

    ok = m.edge_vs_odds >= C.MIN_EDGE_VS_ODDS
    results.append(f"edge_vs_odds={m.edge_vs_odds:.2%} {'ok' if ok else 'fail'}")
    passed += int(ok)

    ok = m.unique_categories >= C.MIN_MARKET_CATEGORIES
    results.append(f"categories={m.unique_categories} {'ok' if ok else 'fail'}")
    passed += int(ok)

    ok = m.positive_weeks_pct >= C.MIN_POSITIVE_WEEKS_PCT
    results.append(f"pos_weeks={m.positive_weeks_pct:.0%} {'ok' if ok else 'fail'}")
    passed += int(ok)

    low, high = C.POSITION_SIZE_RANGE
    ok = low <= m.avg_position_size <= high
    results.append(f"avg_size=${m.avg_position_size:.0f} {'ok' if ok else 'fail'}")
    passed += int(ok)

    ok = m.edge_vs_odds > 0
    results.append(f"entry_timing={'pre-move' if ok else 'post-move'} {'ok' if ok else 'fail'}")
    passed += int(ok)

    return passed, results


def check_tier3_alerts(m: WalletMetrics) -> list[str]:
    alerts: list[str] = []
    if m.win_rate >= 1.0 and m.total_trades < 20:
        alerts.append("100% win rate with <20 trades (luck/insider)")
    if m.track_record_days < 30 and m.total_pnl > 5000:
        alerts.append("wallet <1mo with high PnL (single-use insider)")
    if m.trades_per_month > C.BOT_MAX_TRADES_PER_MONTH:
        alerts.append(f"extreme freq: {m.trades_per_month:.0f}/mo (market maker)")
    return alerts


def full_filter_pipeline(m: WalletMetrics) -> tuple[bool, dict]:
    report: dict = {
        "address": m.address,
        "tier1": None,
        "tier2": None,
        "tier3": None,
        "bot": None,
        "final": False,
    }

    t1_ok, t1_reason = passes_tier1(m)
    report["tier1"] = {"pass": t1_ok, "reason": t1_reason}
    if not t1_ok:
        return False, report

    t3_alerts = check_tier3_alerts(m)
    report["tier3"] = {"alerts": t3_alerts, "pass": len(t3_alerts) == 0}
    if t3_alerts:
        return False, report

    t2_count, t2_results = count_tier2_passes(m)
    t2_ok = t2_count >= C.TIER2_MIN_PASS
    report["tier2"] = {"passed": t2_count, "of": 6, "pass": t2_ok, "details": t2_results}
    if not t2_ok:
        return False, report

    bot_tests = 0
    bot_details: list[str] = []

    ok = m.interval_cv >= C.BOT_INTERVAL_CV_MIN
    bot_tests += int(ok)
    bot_details.append(f"interval_cv={m.interval_cv:.2f} {'ok' if ok else 'fail'}")

    ok = m.size_cv >= C.BOT_SIZE_CV_MIN
    bot_tests += int(ok)
    bot_details.append(f"size_cv={m.size_cv:.2f} {'ok' if ok else 'fail'}")

    # Test 3 (delay correlation) is cross-wallet — skipped here, evaluated elsewhere.
    bot_details.append("corr_delay=deferred (not counted)")

    ok = m.unique_markets_pct >= C.BOT_MIN_UNIQUE_MARKETS_PCT
    bot_tests += int(ok)
    bot_details.append(f"unique_mkts={m.unique_markets_pct:.0%} {'ok' if ok else 'fail'}")

    ok = m.trades_per_month <= C.BOT_MAX_TRADES_PER_MONTH
    bot_tests += int(ok)
    bot_details.append(f"freq={m.trades_per_month:.0f}/mo {'ok' if ok else 'fail'}")

    bot_ok = bot_tests >= C.BOT_MIN_TESTS_PASS
    report["bot"] = {
        "passed": bot_tests,
        "of": 4,
        "pass": bot_ok,
        "details": bot_details,
    }

    report["final"] = bot_ok
    return bot_ok, report
