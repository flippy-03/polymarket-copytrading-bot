"""
Cross-wallet bot detection tests (tests 3 and 4 from the spec).

Intra-wallet tests (1, 2, 5) are computed in wallet_analyzer and evaluated in
wallet_filter. This module covers the tests that require comparing a target
against other wallets' trade histories.
"""
from collections import defaultdict

import numpy as np


def test_delay_correlation(
    target_trades: list[dict],
    whale_trades_by_wallet: dict[str, list[dict]],
    max_delay_seconds: int = 60,
    min_correlation: float = 0.70,
) -> tuple[bool, dict]:
    """
    Test 3: detect wallets that trade consistently N seconds after another wallet
    in the same markets (copier behavior).
    Returns (is_human, details).
    """
    target_by_market: dict[str, list[int]] = defaultdict(list)
    for t in target_trades:
        cid = t.get("conditionId")
        ts = int(t.get("timestamp") or 0)
        if cid and ts:
            target_by_market[cid].append(ts)

    correlations: dict[str, dict] = {}
    for whale_addr, whale_trades in whale_trades_by_wallet.items():
        whale_by_market: dict[str, list[int]] = defaultdict(list)
        for t in whale_trades:
            cid = t.get("conditionId")
            ts = int(t.get("timestamp") or 0)
            if cid and ts:
                whale_by_market[cid].append(ts)

        common = set(target_by_market.keys()) & set(whale_by_market.keys())
        if len(common) < 3:
            continue

        delays: list[int] = []
        for mkt in common:
            for t_ts in target_by_market[mkt]:
                for w_ts in sorted(whale_by_market[mkt]):
                    delay = t_ts - w_ts
                    if 0 < delay <= max_delay_seconds:
                        delays.append(delay)
                        break

        if len(delays) >= 5:
            mean = float(np.mean(delays))
            std = float(np.std(delays))
            cv = std / mean if mean > 0 else 1.0
            consistency = 1 - min(cv, 1)
            correlations[whale_addr] = {
                "avg_delay": mean,
                "std_delay": std,
                "consistency": consistency,
                "n_matches": len(delays),
            }

    if not correlations:
        return True, {"result": "no_correlation_found"}

    top_wallet = max(correlations, key=lambda w: correlations[w]["consistency"])
    top = correlations[top_wallet]
    is_human = top["consistency"] < min_correlation
    return is_human, {
        "most_correlated_wallet": top_wallet,
        "consistency_score": top["consistency"],
        "avg_delay_seconds": top["avg_delay"],
        "is_human": is_human,
    }


def test_market_originality(
    target_trades: list[dict],
    whale_markets: set[str],
    min_unique_pct: float = 0.15,
) -> tuple[bool, float]:
    """
    Test 4: % of the target's markets that are NOT traded by known whales.
    Returns (is_original, pct_unique).
    """
    target_markets = {t.get("conditionId") for t in target_trades if t.get("conditionId")}
    if not target_markets:
        return False, 0.0
    unique = target_markets - whale_markets
    pct = len(unique) / len(target_markets)
    return pct >= min_unique_pct, pct
