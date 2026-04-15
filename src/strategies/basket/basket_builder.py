"""
Basket Consensus — build thematic baskets (crypto / economics / politics).

Flow:
1. Discover category tags via Gamma API.
2. For each category: fetch top markets, pull top holders/traders.
3. Analyze each candidate wallet with wallet_analyzer.
4. Specialist filter: ≥BASKET_MIN_CATEGORY_PNL_PCT of wallet PnL from this category.
5. Top-N by composite score (never empty basket); floor check replaces hard-gate pipeline.
6. Persist to baskets / basket_wallets.

Key design changes vs original spec:
- Candidates ranked by total USDC gained in resolved markets (not by count of markets).
- Category detection uses conditionIds from Gamma tags (not keyword matching).
- Specialist filter: cat_pnl / total_pnl >= threshold (not just "has traded in category").
- Top-N selection: take best N by composite score; Tier1 is sanity floor, not eliminator.
"""
import datetime
import time
from collections import Counter, defaultdict

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.common.wallet_analyzer import WalletMetrics, _usdc, analyze_wallet
from src.strategies.common.wallet_filter import (
    full_filter_pipeline,
    passes_tier1,
)
from src.utils.logger import logger


def _composite_score(m: WalletMetrics, cat_pnl_pct: float = 0.0) -> float:
    pf = min(m.profit_factor, 5.0) if m.profit_factor != float("inf") else 5.0
    # PnL bonus: 0..5 pts, saturates at $5000 net profit.
    pnl_bonus = min(max(m.total_pnl / 1000.0, 0.0), 5.0)
    # Specialist bonus: 0..3 pts for category concentration (100% = 3 pts).
    specialist_bonus = min(cat_pnl_pct * 3.0, 3.0)
    return (
        pf * 0.22
        + (m.edge_vs_odds * 100) * 0.18
        + min(m.trades_per_month / 20, 1) * 0.10
        + m.positive_weeks_pct * 0.10
        + (0 if m.is_likely_bot else 1) * 0.05
        + pnl_bonus * 0.15
        + specialist_bonus * 0.20
    )


def _category_pnl(
    trades: list[dict],
    positions: list[dict] | None,
    cids: set[str],
) -> float:
    """
    PnL of a wallet restricted to markets in `cids` (the basket's category).
    Uses /positions cashPnl as authority (same hierarchy as analyze_wallet).
    Falls back to activity net for fully-exited markets not in /positions.
    """
    pnl = 0.0
    pos_cids: set[str] = set()
    for p in positions or []:
        cid = p.get("conditionId")
        if cid and cid in cids:
            pnl += float(p.get("cashPnl") or 0)
            pos_cids.add(cid)
    # Markets fully exited (no row in /positions for this cid)
    by_cid: dict[str, list] = defaultdict(list)
    for t in trades:
        cid = t.get("conditionId")
        if cid and cid in cids and cid not in pos_cids:
            by_cid[cid].append(t)
    for cid, mkt_trades in by_cid.items():
        sells = [t for t in mkt_trades if t.get("side") == "SELL"]
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        if sells:
            pnl += sum(_usdc(t) for t in sells) - sum(_usdc(t) for t in buys)
    return pnl


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
        # Rank by total USDC gained (not count of markets). A wallet with $500
        # gain in 2 markets is a better signal than one with $1 in 8 markets.
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

        # Build the authoritative set of conditionIds for this category.
        # Used later for the specialist filter (replaces keyword matching).
        all_category_cids: set[str] = {
            m["conditionId"] for m in (unique + unique_resolved)
            if m.get("conditionId")
        }
        logger.info(f"  category conditionIds (active+resolved): {len(all_category_cids)}")

        wallet_total_gain: dict[str, float] = defaultdict(float)
        market_appearances: Counter = Counter()

        for mkt in unique_resolved[:30]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                mkt_trades = self.data.get_market_trades(cid, limit=300)
                wallet_net: dict[str, float] = defaultdict(float)
                for t in mkt_trades:
                    addr = t.get("proxyWallet")
                    if not addr:
                        continue
                    market_appearances[addr] += 1
                    try:
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
                for addr, net in wallet_net.items():
                    if net > 0:
                        wallet_total_gain[addr] += net
            except Exception as e:
                logger.warning(f"  resolved trades({cid[:12]}) failed: {e}")
            time.sleep(0.15)

        # Rank by total USDC gained; exclude market makers (>20 markets)
        candidates = sorted(
            [a for a, g in wallet_total_gain.items() if market_appearances[a] <= 20],
            key=lambda a: wallet_total_gain[a],
            reverse=True,
        )[:150]
        top_gain = f"${wallet_total_gain[candidates[0]]:.0f}" if candidates else "—"
        logger.info(f"  candidates ranked by total gain: {len(candidates)} (top: {top_gain})")

        # Supplement with active market traders if resolved pool is thin
        if len(candidates) < 15:
            logger.info("  supplementing with active market traders (pool thin)")
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
            existing = set(candidates)
            candidates += [a for a, _ in active_freq.most_common(60) if a not in existing]

        logger.info(f"  candidates for analysis: {len(candidates)}")

        # ── Step 3: analyze candidates + specialist filter ───────────────────
        # Store (metrics, trades, positions, cat_pnl_pct) for scoring step.
        analyzed: list[tuple[WalletMetrics, list[dict], list[dict] | None, float]] = []
        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )
        skipped_few_trades = 0
        for addr in candidates[:C.BASKET_POOL_CANDIDATES]:
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    skipped_few_trades += 1
                    continue
                try:
                    positions = self.data.get_wallet_positions(addr, limit=500)
                except Exception as e:
                    logger.warning(f"  positions {addr[:10]}… failed: {e}; trades-only")
                    positions = None
                metrics = analyze_wallet(trades, addr, positions)

                # Specialist signal: what fraction of the wallet's PnL came from
                # this category's known conditionIds. Used as ranking bonus only
                # (not as a hard filter) because our cids window (~90 markets) is
                # too small relative to a wallet's 4-month history — a genuine
                # crypto specialist who traded 300 markets would fail a hard gate.
                # Discovery from category resolved markets already ensures engagement.
                cat_pnl = _category_pnl(trades, positions, all_category_cids)
                cat_pnl_pct = (cat_pnl / metrics.total_pnl) if metrics.total_pnl > 0 else 0.0

                analyzed.append((metrics, trades, positions, cat_pnl_pct))
            except Exception as e:
                logger.warning(f"  analyze {addr[:10]}… failed: {e}")
            time.sleep(0.2)

        logger.info(
            f"  analyzed: {len(analyzed)} "
            f"(skipped {skipped_few_trades} <{C.MIN_TRADES_TOTAL} trades)"
        )

        # Sample log for first 5
        for metrics, _, _, cat_pnl_pct in analyzed[:5]:
            t1_ok, t1_reason = passes_tier1(metrics)
            logger.info(
                f"  sample {metrics.address[:10]}… "
                f"trades={metrics.total_trades} "
                f"WR={metrics.win_rate:.1%} "
                f"days={metrics.track_record_days} "
                f"total_pnl=${metrics.total_pnl:.0f} "
                f"cat_pnl={cat_pnl_pct:.0%} "
                f"pnl30d=${metrics.pnl_30d:.0f} "
                f"→ T1={'OK' if t1_ok else t1_reason}"
            )

        # ── Step 4: score all candidates, persist metrics ────────────────────
        # Full pipeline used for DB persistence and reporting only.
        # Selection uses composite score, NOT pass/fail gating.
        scored: list[tuple[WalletMetrics, float, float]] = []  # (metrics, score, cat_pnl_pct)
        for metrics, _trades, _positions, cat_pnl_pct in analyzed:
            ok, report = full_filter_pipeline(metrics)
            t1 = report.get("tier1") or {}
            t2 = report.get("tier2") or {}
            t3 = report.get("tier3") or {}
            bot = report.get("bot") or {}
            score = _composite_score(metrics, cat_pnl_pct)
            try:
                db.save_wallet_metrics(
                    metrics,
                    tier1_pass=bool(t1.get("pass")),
                    tier2_score=int(t2.get("passed") or 0),
                    tier3_alerts=list(t3.get("alerts") or []),
                    is_bot=not bool(bot.get("pass", True)),
                    bot_score=int(bot.get("passed") or 0),
                    composite_score=score,
                    run_id=self.run_id,
                )
            except Exception as e:
                logger.warning(f"  save_wallet_metrics failed for {metrics.address[:10]}…: {e}")

            # Sanity floor (hard gates): positive PnL, not a bot, not degenerate track record.
            # Everything else is handled by composite score ranking.
            t1_ok, _ = passes_tier1(metrics)
            if not t1_ok or metrics.is_likely_bot:
                continue
            scored.append((metrics, score, cat_pnl_pct))

        scored.sort(key=lambda x: x[1], reverse=True)

        logger.info(f"  passed floor: {len(scored)}/{len(analyzed)}")
        if len(scored) < len(analyzed):
            from collections import Counter as _C
            floor_fails = [
                m.address for m, _, _ in analyzed
                if not any(m.address == s[0].address for s in scored)
            ]
            logger.info(f"  floor-failed: {len(floor_fails)} wallets")

        # ── Step 5: Top-N by composite score ────────────────────────────────
        selected = scored[:C.BASKET_MAX_WALLETS]

        for i, (w, score, cat_pct) in enumerate(selected):
            logger.info(
                f"    {i+1}. {w.address[:12]}… "
                f"score={score:.3f} cat={cat_pct:.0%} "
                f"WR={w.win_rate:.0%} PF={w.profit_factor:.1f} "
                f"pnl=${w.total_pnl:.0f} edge={w.edge_vs_odds:.1%}"
            )

        # ── Step 6: persist ──────────────────────────────
        basket_id = db.get_or_create_basket(category.upper())
        payload = [
            {
                "address": w.address,
                "rank_score": round(score, 4),
                "rank_position": i + 1,
            }
            for i, (w, score, _) in enumerate(selected)
        ]
        db.replace_basket_wallets(basket_id, payload, run_id=self.run_id)

        return {
            "basket_id": basket_id,
            "category": category,
            "wallets": [w.address for w, _, _ in selected],
            "candidates_found": len(candidates),
            "analyzed": len(analyzed),
            "passed_floor": len(scored),
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
