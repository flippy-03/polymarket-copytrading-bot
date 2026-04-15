"""
Basket Consensus — build thematic baskets (crypto / economics / politics).

Flow:
1. Discover category tags via Gamma API.
2. For each category: fetch top markets, pull top holders/traders.
3. Analyze each candidate wallet with wallet_analyzer.
4. Run full_filter_pipeline (Tier 1/2/3 + bot).
5. Rank by composite score, pick top 5-10.
6. Persist to baskets / basket_wallets.
"""
import datetime
import time
from collections import Counter, defaultdict

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.common.wallet_analyzer import WalletMetrics, analyze_wallet
from src.strategies.common.wallet_filter import (
    check_tier3_alerts,
    count_tier2_passes,
    full_filter_pipeline,
    passes_tier1,
)
from src.utils.logger import logger


def _composite_score(m: WalletMetrics) -> float:
    pf = min(m.profit_factor, 5.0) if m.profit_factor != float("inf") else 5.0
    return (
        pf * 0.30
        + (m.edge_vs_odds * 100) * 0.25
        + min(m.trades_per_month / 20, 1) * 0.20
        + m.positive_weeks_pct * 0.15
        + (0 if m.is_likely_bot else 1) * 0.10
    )


class BasketBuilder:
    STRATEGY = "BASKET"

    def __init__(self):
        self.gamma = GammaClient()
        self.data = DataClient()
        self.run_id = db.get_active_run(self.STRATEGY)

    def close(self):
        self.gamma.close()
        self.data.close()

    def build_basket(
        self,
        category: str,
        tag_ids: list[int],
        max_wallets: int = C.BASKET_MAX_WALLETS,
    ) -> dict:
        logger.info(f"Building basket: {category.upper()} (tags={tag_ids})")

        # ── Step 1: discover markets ─────────────────────
        markets: list[dict] = []
        for tag_id in tag_ids:
            try:
                batch = self.gamma.get_active_markets(
                    tag_id=tag_id,
                    min_volume_24h=C.MIN_LIQUIDITY_24H,
                    limit=50,
                )
                markets.extend(batch)
            except Exception as e:
                logger.warning(f"get_active_markets(tag_id={tag_id}) failed: {e}")
            time.sleep(0.2)

        seen: set[str] = set()
        unique: list[dict] = []
        for m in markets:
            cid = m.get("conditionId")
            if cid and cid not in seen:
                seen.add(cid)
                unique.append(m)

        cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=7)
        cutoff_iso = cutoff.isoformat() + "Z"
        short_term = [m for m in unique if (m.get("endDate") or "9999") <= cutoff_iso]
        target_markets = short_term if len(short_term) >= 5 else unique[:20]
        logger.info(f"  markets: {len(unique)} unique, {len(short_term)} <=7d, using {len(target_markets)}")

        # ── Step 2: collect candidates from holders ──────
        freq: Counter = Counter()
        for mkt in target_markets[:20]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                holders = self.data.get_market_holders(cid, limit=50)
                for h in holders:
                    addr = h.get("proxyWallet") or h.get("address")
                    if addr:
                        freq[addr] += 1
            except Exception as e:
                logger.warning(f"  holders({cid[:12]}) failed: {e}")
            time.sleep(0.15)

        # Prefer wallets seen in ≥2 markets; fall back to any presence if pool is small
        candidates = [addr for addr, count in freq.most_common(60) if count >= 2]
        if len(candidates) < 10:
            candidates = [addr for addr, count in freq.most_common(60) if count >= 1]
            logger.info(f"  candidates (≥1 market, fallback): {len(candidates)}")
        else:
            logger.info(f"  candidates with ≥2 market presence: {len(candidates)}")

        # ── Step 3: analyze candidates ───────────────────
        analyzed: list[tuple[WalletMetrics, list[dict]]] = []
        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )
        for i, addr in enumerate(candidates[:30]):
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    continue
                metrics = analyze_wallet(trades, addr)
                analyzed.append((metrics, trades))
            except Exception as e:
                logger.warning(f"  analyze {addr[:10]}… failed: {e}")
            time.sleep(0.2)
        logger.info(f"  analyzed wallets with enough data: {len(analyzed)}")

        # ── Step 4: filter pipeline ──────────────────────
        passed: list[WalletMetrics] = []
        rejected: list[dict] = []
        for metrics, _trades in analyzed:
            ok, report = full_filter_pipeline(metrics)
            # Persist wallet_metrics snapshot
            t1 = report.get("tier1") or {}
            t2 = report.get("tier2") or {}
            t3 = report.get("tier3") or {}
            bot = report.get("bot") or {}
            try:
                db.save_wallet_metrics(
                    metrics,
                    tier1_pass=bool(t1.get("pass")),
                    tier2_score=int(t2.get("passed") or 0),
                    tier3_alerts=list(t3.get("alerts") or []),
                    is_bot=not bool(bot.get("pass", True)),
                    bot_score=int(bot.get("passed") or 0),
                    composite_score=_composite_score(metrics) if ok else None,
                    run_id=self.run_id,
                )
            except Exception as e:
                logger.warning(f"  save_wallet_metrics failed for {metrics.address[:10]}…: {e}")
            if ok:
                passed.append(metrics)
            else:
                for tier in ("tier1", "tier3", "tier2", "bot"):
                    tier_report = report.get(tier) or {}
                    if tier_report and not tier_report.get("pass", True):
                        rejected.append({
                            "address": metrics.address,
                            "reason": tier_report.get("reason") or str(tier_report),
                        })
                        break

        logger.info(f"  passed filters: {len(passed)}/{len(analyzed)}")

        # ── Step 5: rank and pick ────────────────────────
        scored = sorted(passed, key=_composite_score, reverse=True)
        selected = scored[:max_wallets]

        for i, w in enumerate(selected):
            logger.info(
                f"    {i+1}. {w.address[:12]}… "
                f"WR={w.win_rate:.0%} PF={w.profit_factor:.1f} "
                f"edge={w.edge_vs_odds:.1%} freq={w.trades_per_month:.0f}/mo"
            )

        # ── Step 6: persist ──────────────────────────────
        basket_id = db.get_or_create_basket(category.upper())
        payload = [
            {
                "address": w.address,
                "rank_score": round(_composite_score(w), 4),
                "rank_position": i + 1,
            }
            for i, w in enumerate(selected)
        ]
        db.replace_basket_wallets(basket_id, payload, run_id=self.run_id)

        return {
            "basket_id": basket_id,
            "category": category,
            "wallets": [w.address for w in selected],
            "rejected_count": len(rejected),
            "markets_scanned": len(unique),
            "candidates_found": len(candidates),
        }

    def build_all_baskets(self) -> dict[str, dict]:
        logger.info("Discovering category tag ids from Gamma API…")
        tag_map = self.gamma.discover_category_tags()
        logger.info(f"Tags found: { {k: len(v) for k, v in tag_map.items()} }")

        baskets: dict[str, dict] = {}
        for category in ("crypto", "economics", "politics"):
            tag_ids = tag_map.get(category) or []
            if not tag_ids:
                logger.warning(f"No tags found for {category}; skipping")
                continue
            baskets[category] = self.build_basket(category, tag_ids)
            time.sleep(1)
        return baskets
