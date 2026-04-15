"""
Scalper Pool Builder — cross-category discovery of high-frequency profitable
traders. Stricter filters than basket: ≤5d avg holding, ≥12 trades/month.
Ranks by estimated Sharpe 14d and persists top N to scalper_pool.
"""
import datetime
import time
from collections import Counter, defaultdict

import numpy as np

from src.strategies.common import config as C, db
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.common.wallet_analyzer import WalletMetrics, _usdc, analyze_wallet
from src.strategies.common.wallet_filter import full_filter_pipeline
from src.utils.logger import logger


def estimate_sharpe_14d(trades: list[dict]) -> float:
    now_ts = int(time.time())
    ts_14d = now_ts - 14 * 86400
    recent = [t for t in trades if int(t.get("timestamp") or 0) >= ts_14d]
    if len(recent) < 5:
        return 0.0

    daily_pnl: dict[datetime.date, float] = defaultdict(float)
    for t in recent:
        day = datetime.datetime.utcfromtimestamp(int(t["timestamp"])).date()
        # Use shared fallback so wallets with missing usdcSize still contribute.
        usdc = _usdc(t)
        if (t.get("side") or "").upper() == "SELL":
            daily_pnl[day] += usdc
        else:
            daily_pnl[day] -= usdc

    if len(daily_pnl) < 3:
        return 0.0

    returns = np.array(list(daily_pnl.values()), dtype=float)
    std = float(returns.std())
    if std == 0:
        return 0.0
    return float((returns.mean() / std) * np.sqrt(365))


class ScalperPoolBuilder:
    STRATEGY = "SCALPER"

    def __init__(self):
        self.gamma = GammaClient()
        self.data = DataClient()
        self.run_id = db.get_active_run(self.STRATEGY)

    def close(self):
        self.gamma.close()
        self.data.close()

    def build_pool(self, pool_size: int = C.SCALPER_POOL_SIZE) -> dict:
        logger.info(f"Building scalper pool (target={pool_size})")

        # ── Step 1: top markets cross-category ───────────
        try:
            markets = self.gamma.get_active_markets(
                min_volume_24h=C.MIN_LIQUIDITY_24H, limit=100
            )
        except Exception as e:
            logger.warning(f"get_active_markets failed: {e}")
            markets = []
        logger.info(f"  markets: {len(markets)}")

        # ── Step 2: collect traders from RESOLVED markets ─
        # Same profitability-based approach as basket builder:
        # find wallets that netted positive USDC (SELL > BUY) in ≥1 resolved market.
        # This pre-screens for manual traders with real exit discipline.
        resolved = []
        try:
            # cross-category: fetch resolved markets without tag filter
            resolved = self.gamma.get_resolved_markets(limit=40)
        except Exception as e:
            logger.warning(f"  get_resolved_markets failed: {e}")
        logger.info(f"  resolved markets for candidate discovery: {len(resolved)}")

        profitable_markets: Counter = Counter()
        market_appearances: Counter = Counter()
        for mkt in resolved[:30]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                mkt_trades = self.data.get_market_trades(cid, limit=300)
                wallet_net: dict[str, float] = defaultdict(float)
                for t in mkt_trades:
                    addr = t.get("proxyWallet") or t.get("address")
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
                        profitable_markets[addr] += 1
            except Exception as e:
                logger.warning(f"  resolved_trades({cid[:12]}) failed: {e}")
            time.sleep(0.15)

        # Candidates: profitable in ≥1 resolved market, not market makers (≤20 markets)
        candidates = [
            addr for addr, wins in profitable_markets.most_common(150)
            if wins >= 1 and market_appearances[addr] <= 20
        ]

        # Supplement with active markets if resolved pool is thin
        if len(candidates) < 15:
            logger.info("  supplementing with active market traders")
            freq: Counter = Counter()
            for mkt in markets[:20]:
                cid = mkt.get("conditionId")
                if not cid:
                    continue
                try:
                    mkt_trades = self.data.get_market_trades(cid, limit=200)
                    for t in mkt_trades:
                        addr = t.get("proxyWallet") or t.get("address")
                        if addr:
                            freq[addr] += 1
                except Exception as e:
                    logger.warning(f"  market_trades({cid[:12]}) failed: {e}")
                time.sleep(0.15)
            existing = set(candidates)
            candidates += [a for a, _ in freq.most_common(60) if a not in existing]

        logger.info(f"  candidates (profitable in resolved markets): {len(candidates)}")

        # ── Step 3: analyze + scalper-specific filters ───
        analyzed: list[tuple[WalletMetrics, list[dict]]] = []
        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )
        for addr in candidates[:60]:
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    continue
                # Positions = authoritative per-market PnL (hold-to-resolution safe).
                try:
                    positions = self.data.get_wallet_positions(addr, limit=500)
                except Exception as e:
                    logger.warning(f"  positions {addr[:10]}… failed: {e}; analyzing trades-only")
                    positions = None
                metrics = analyze_wallet(trades, addr, positions)
                if metrics.avg_holding_period_hours > 5 * 24:
                    continue
                if metrics.trades_per_month < 12:
                    continue
                analyzed.append((metrics, trades))
            except Exception as e:
                logger.warning(f"  analyze {addr[:10]}… failed: {e}")
            time.sleep(0.2)
        logger.info(f"  passed scalper-specific: {len(analyzed)}")

        # ── Step 4: standard pipeline ────────────────────
        passed: list[tuple[WalletMetrics, list[dict]]] = []
        for metrics, trades in analyzed:
            ok, report = full_filter_pipeline(metrics)
            t1 = report.get("tier1") or {}
            t2 = report.get("tier2") or {}
            t3 = report.get("tier3") or {}
            bot = report.get("bot") or {}
            sharpe = estimate_sharpe_14d(trades)
            try:
                db.save_wallet_metrics(
                    metrics,
                    tier1_pass=bool(t1.get("pass")),
                    tier2_score=int(t2.get("passed") or 0),
                    tier3_alerts=list(t3.get("alerts") or []),
                    is_bot=not bool(bot.get("pass", True)),
                    bot_score=int(bot.get("passed") or 0),
                    sharpe_14d=sharpe,
                    run_id=self.run_id,
                )
            except Exception as e:
                logger.warning(f"  save_wallet_metrics failed for {metrics.address[:10]}…: {e}")
            if ok:
                passed.append((metrics, trades))
        logger.info(f"  passed full pipeline: {len(passed)}")

        # ── Step 5: rank by Sharpe 14d ───────────────────
        scored = [
            (m, estimate_sharpe_14d(trades)) for m, trades in passed
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        selected = scored[:pool_size]

        for i, (m, s) in enumerate(selected):
            logger.info(
                f"    {i+1}. {m.address[:12]}… "
                f"Sharpe={s:.2f} WR={m.win_rate:.0%} freq={m.trades_per_month:.0f}/mo"
            )

        entries = [
            {
                "address": m.address,
                "status": "POOL",
                "sharpe_14d": round(s, 4),
                "rank_position": i + 1,
                "capital_allocated_usd": 0,
            }
            for i, (m, s) in enumerate(selected)
        ]
        db.set_scalper_pool(entries, run_id=self.run_id)

        return {
            "pool_size": len(selected),
            "wallets": [e["address"] for e in entries],
        }
