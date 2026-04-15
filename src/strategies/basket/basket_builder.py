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
    # PnL bonus: 0..5 pts, saturates at $5000 net profit.
    # Tier 1 already rejects negative total_pnl, so this is always ≥0 here.
    pnl_bonus = min(max(m.total_pnl / 1000.0, 0.0), 5.0)
    return (
        pf * 0.25
        + (m.edge_vs_odds * 100) * 0.20
        + min(m.trades_per_month / 20, 1) * 0.15
        + m.positive_weeks_pct * 0.10
        + (0 if m.is_likely_bot else 1) * 0.10
        + pnl_bonus * 0.20
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

        # ── Step 2: collect candidates from resolved markets ─────────────────────
        # Strategy: from resolved markets, find wallets that were PROFITABLE
        # (net USDC positive = SELL > BUY in that market). These are wallets that
        # manually exited with gains — exactly the copy-worthy signal we need.
        # Hold-to-resolution bots (BUY-only) are excluded naturally.

        # 2a — get resolved markets for this category
        resolved_markets: list[dict] = []
        for tag_id in tag_ids:
            try:
                batch = self.gamma.get_resolved_markets(tag_id=tag_id, limit=40)
                resolved_markets.extend(batch)
            except Exception as e:
                logger.warning(f"  get_resolved_markets(tag_id={tag_id}) failed: {e}")
            time.sleep(0.2)
        seen_resolved: set[str] = set()
        unique_resolved: list[dict] = []
        for m in resolved_markets:
            cid = m.get("conditionId")
            if cid and cid not in seen_resolved:
                seen_resolved.add(cid)
                unique_resolved.append(m)
        logger.info(f"  resolved markets found: {len(unique_resolved)}")

        # 2b — for each resolved market, find wallets with positive USDC flow
        # profitable_markets[addr] = count of resolved markets where wallet netted > 0
        profitable_markets: Counter = Counter()
        market_appearances: Counter = Counter()

        for mkt in unique_resolved[:30]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                mkt_trades = self.data.get_market_trades(cid, limit=300)
                # Group by wallet and compute net USDC.
                # Market /trades uses `size` (shares) + `price`, not `usdcSize`.
                wallet_net: dict[str, float] = defaultdict(float)
                for t in mkt_trades:
                    addr = t.get("proxyWallet")
                    if not addr:
                        continue
                    market_appearances[addr] += 1
                    try:
                        # usdcSize is on wallet /activity; market /trades uses size*price
                        usdc = (
                            float(t["usdcSize"])
                            if "usdcSize" in t
                            else float(t.get("size") or 0) * float(t.get("price") or 0.5)
                        )
                    except (TypeError, ValueError):
                        usdc = 0.0
                    if t.get("side") == "SELL":
                        wallet_net[addr] += usdc
                    else:
                        wallet_net[addr] -= usdc
                # Count profitable wallets in this market
                for addr, net in wallet_net.items():
                    if net > 0:
                        profitable_markets[addr] += 1
            except Exception as e:
                logger.warning(f"  resolved trades({cid[:12]}) failed: {e}")
            time.sleep(0.15)

        # 2c — candidates ranked by number of profitable resolved markets
        # Exclude market makers (appear in >20 markets) and one-offs (0 profitable markets)
        all_profitable = [
            addr for addr, wins in profitable_markets.most_common(200)
            if wins >= 1 and market_appearances[addr] <= 20
        ]
        profitable_count = len(all_profitable)
        logger.info(f"  profitable in ≥1 resolved market: {profitable_count}")

        # 2d — supplement with active market traders if profitable pool is thin
        if profitable_count < 15:
            logger.info(f"  supplementing with active market traders (pool thin)")
            active_freq: Counter = Counter()
            for mkt in target_markets[:15]:
                cid = mkt.get("conditionId")
                if not cid:
                    continue
                try:
                    mkt_trades = self.data.get_market_trades(cid, limit=200)
                    for t in mkt_trades:
                        addr = t.get("proxyWallet")
                        if addr:
                            active_freq[addr] += 1
                except Exception as e:
                    logger.warning(f"  active trades({cid[:12]}) failed: {e}")
                time.sleep(0.15)
            # Add addresses not already in profitable pool
            existing = set(all_profitable)
            supplement = [a for a, _ in active_freq.most_common(50) if a not in existing]
            all_profitable.extend(supplement[:20])

        candidates = all_profitable
        logger.info(f"  candidates for analysis: {len(candidates)}")

        # ── Step 3: analyze candidates ───────────────────
        analyzed: list[tuple[WalletMetrics, list[dict]]] = []
        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )
        skipped_few_trades = 0
        skipped_off_category = 0
        for i, addr in enumerate(candidates[:50]):
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    skipped_few_trades += 1
                    continue
                # Positions = authoritative per-market PnL (includes hold-to-resolution).
                try:
                    positions = self.data.get_wallet_positions(addr, limit=500)
                except Exception as e:
                    logger.warning(f"  positions {addr[:10]}… failed: {e}; analyzing trades-only")
                    positions = None
                metrics = analyze_wallet(trades, addr, positions)
                # Category-specialist filter: require the wallet's trade history
                # to include the target category. Wallets that were profitable
                # in one resolved market but primarily trade other categories
                # are excluded from this basket.
                if category.lower() not in [c.lower() for c in metrics.categories]:
                    skipped_off_category += 1
                    continue
                analyzed.append((metrics, trades))
            except Exception as e:
                logger.warning(f"  analyze {addr[:10]}… failed: {e}")
            time.sleep(0.2)
        logger.info(
            f"  analyzed wallets with enough data: {len(analyzed)} "
            f"(skipped {skipped_few_trades} <{C.MIN_TRADES_TOTAL} trades, "
            f"{skipped_off_category} off-category)"
        )
        # Sample log: show metrics for first 5 analyzed wallets
        for metrics, _ in analyzed[:5]:
            from src.strategies.common.wallet_filter import passes_tier1
            t1_ok, t1_reason = passes_tier1(metrics)
            logger.info(
                f"  sample {metrics.address[:10]}… "
                f"trades={metrics.total_trades} "
                f"WR={metrics.win_rate:.1%} "
                f"days={metrics.track_record_days} "
                f"total_pnl={metrics.total_pnl:.0f} "
                f"pnl30d={metrics.pnl_30d:.0f} "
                f"freq={metrics.trades_per_month:.1f}/mo "
                f"→ T1={'OK' if t1_ok else t1_reason}"
            )

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
        if rejected:
            from collections import Counter as _C
            reason_counts = _C(r["reason"] for r in rejected)
            logger.info(f"  rejection reasons: {dict(reason_counts.most_common(8))}")

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
