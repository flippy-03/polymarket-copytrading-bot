"""
Scalper V2 Rotation Engine — performance-degradation health check.

Replaces the V1 forced weekly rotation. Instead, every HEALTH_CHECK_HOURS
(default 72h) it evaluates each titular's current metrics and only rotates
those showing genuine degradation.

Degradation triggers (any one fires → replacement):
  1. Composite score drops below 0.40
  2. Per-titular consecutive losses >= loss_limit (CB individual already tripped)
  3. Inactivity: last_7d_trades == 0 AND last_30d_trades < 3
  4. Declining trend: hit_rate_trend == "DECLINING" AND momentum_score < -0.3

When a titular is replaced:
  - 30/60/90 day cooldown via cooldown_manager
  - Open positions stay open (resolved naturally or by trailing stop)
  - Best available candidate selected via pool_selector
"""
from __future__ import annotations

from src.strategies.common import config as C, db
from src.strategies.scalper import cooldown_manager
from src.strategies.scalper.pool_selector import ScalperPoolSelector, _composite_score
from src.utils.logger import logger


class RotationEngine:
    STRATEGY = "SCALPER"

    def __init__(self):
        self.run_id = db.get_active_run(self.STRATEGY)

    def health_check(self, reason: str = "SCHEDULED_HEALTH_CHECK") -> dict:
        """Evaluate all titulars and replace any showing degradation.

        Returns audit dict with check results.
        """
        logger.info(f"Scalper V2 health check: {reason} (run={self.run_id[:8]})")
        titulars = db.list_scalper_pool(status="ACTIVE_TITULAR", run_id=self.run_id)
        if not titulars:
            logger.warning("No active titulars — nothing to check")
            return {"checked": 0, "removed": [], "added": []}

        removed: list[dict] = []
        checked = 0

        for titular in titulars:
            wallet = titular["wallet_address"]
            checked += 1

            # Fetch fresh enriched profile
            profile = db.get_wallet_profile(wallet)
            if not profile:
                logger.debug(f"  {wallet[:10]}… — no enriched profile, skipping check")
                continue

            should_remove, trigger = self._evaluate_titular(titular, profile)

            if should_remove:
                logger.warning(
                    f"  REMOVING {wallet[:10]}… — trigger: {trigger}"
                )
                # Get approved types for cooldown
                approved_types = titular.get("approved_market_types") or []
                best_type = approved_types[0] if approved_types else "unknown"

                # Metrics snapshot for audit
                metrics_snapshot = {
                    "composite_score": titular.get("composite_score"),
                    "per_trader_consecutive_losses": titular.get("per_trader_consecutive_losses"),
                    "hit_rate_trend": profile.get("hit_rate_trend"),
                    "momentum_score": profile.get("momentum_score"),
                    "last_30d_trades": profile.get("last_30d_trades"),
                }

                # Add cooldown for each approved type
                for mtype in approved_types:
                    cooldown_manager.add_cooldown(
                        wallet, mtype, reason=trigger, metrics_snapshot=metrics_snapshot,
                    )

                # Demote to POOL status
                db.update_scalper_status(wallet, "POOL", capital_usd=0, run_id=self.run_id)

                removed.append({
                    "wallet": wallet,
                    "trigger": trigger,
                    "best_type": best_type,
                    "metrics": metrics_snapshot,
                })
            else:
                # Update composite score with fresh data
                self._refresh_scores(titular, profile)

        # Replace removed titulars
        added: list[dict] = []
        if removed:
            current_titulars = db.list_scalper_pool(
                status="ACTIVE_TITULAR", run_id=self.run_id
            )
            slots_to_fill = C.SCALPER_ACTIVE_WALLETS - len(current_titulars)
            if slots_to_fill > 0:
                selector = ScalperPoolSelector(run_id=self.run_id)
                # Load dashboard priority types
                config = db.get_scalper_config(self.run_id)
                priority_types = config.get("priority_market_types", [])

                candidates = selector.select(
                    num_titulars=slots_to_fill,
                    priority_types=priority_types,
                )
                # Filter out wallets already titular
                existing_wallets = {t["wallet_address"] for t in current_titulars}
                candidates = [c for c in candidates if c.wallet not in existing_wallets]

                if candidates:
                    selector.persist_selection(candidates)
                    for c in candidates:
                        added.append({
                            "wallet": c.wallet,
                            "best_type": c.best_type,
                            "score": c.best_score,
                            "approved_types": c.approved_types,
                        })

        # Log rotation audit
        if removed or added:
            try:
                pool = db.list_scalper_pool(run_id=self.run_id)
                db.insert_rotation(
                    reason=reason,
                    removed_titulars=removed,
                    new_titulars=added,
                    pool_snapshot=[{
                        "wallet": r["wallet_address"],
                        "status": r.get("status"),
                        "composite_score": r.get("composite_score"),
                    } for r in pool],
                    run_id=self.run_id,
                )
            except Exception as e:
                logger.warning(f"insert_rotation failed: {e}")

        result = {"checked": checked, "removed": removed, "added": added}
        logger.info(
            f"Health check done: checked={checked}, "
            f"removed={len(removed)}, added={len(added)}"
        )
        return result

    def _evaluate_titular(
        self, titular: dict, profile: dict
    ) -> tuple[bool, str]:
        """Check if a titular should be removed.

        Returns (should_remove, trigger_reason).
        """
        wallet = titular["wallet_address"]

        # 1. Per-titular CB already tripped
        if titular.get("per_trader_is_broken"):
            return True, "CONSECUTIVE_LOSSES"

        # 2. Recompute composite score with fresh profile
        approved_types = titular.get("approved_market_types") or []
        type_hrs = profile.get("type_hit_rates") or {}
        type_pfs = profile.get("type_profit_factors") or {}
        type_tcs = profile.get("type_trade_counts") or {}
        type_sharpes = profile.get("type_sharpe_ratios") or {}

        best_score = 0.0
        for mtype in approved_types:
            if mtype not in type_hrs:
                continue
            score = _composite_score(
                type_hr=type_hrs.get(mtype, 0),
                type_pf=type_pfs.get(mtype, 0),
                type_tc=type_tcs.get(mtype, 0),
                type_sharpe=type_sharpes.get(mtype, 0),
                worst_30d_hr=profile.get("worst_30d_hit_rate") or 0,
                hr_variance=profile.get("hit_rate_variance") or 0.15,
                momentum=profile.get("momentum_score") or 0,
                sharpe_proxy=profile.get("sharpe_proxy") or 0,
                confidence=profile.get("profile_confidence") or "LOW",
                is_priority=False,
            )
            best_score = max(best_score, score)

        if best_score < 0.40:
            return True, "SCORE_DEGRADED"

        # 3. Inactivity
        last_7d = profile.get("last_7d_trades") or 0
        last_30d = profile.get("last_30d_trades") or 0
        if last_7d == 0 and last_30d < 3:
            return True, "INACTIVITY"

        # 4. Declining trend
        trend = profile.get("hit_rate_trend")
        momentum = profile.get("momentum_score") or 0
        if trend == "DECLINING" and momentum < -0.3:
            return True, "DECLINING_TREND"

        return False, ""

    def _refresh_scores(self, titular: dict, profile: dict) -> None:
        """Update composite score on scalper_pool with fresh profile data."""
        approved_types = titular.get("approved_market_types") or []
        type_hrs = profile.get("type_hit_rates") or {}
        type_pfs = profile.get("type_profit_factors") or {}
        type_tcs = profile.get("type_trade_counts") or {}
        type_sharpes = profile.get("type_sharpe_ratios") or {}

        best_score = 0.0
        for mtype in approved_types:
            if mtype not in type_hrs:
                continue
            score = _composite_score(
                type_hr=type_hrs.get(mtype, 0),
                type_pf=type_pfs.get(mtype, 0),
                type_tc=type_tcs.get(mtype, 0),
                type_sharpe=type_sharpes.get(mtype, 0),
                worst_30d_hr=profile.get("worst_30d_hit_rate") or 0,
                hr_variance=profile.get("hit_rate_variance") or 0.15,
                momentum=profile.get("momentum_score") or 0,
                sharpe_proxy=profile.get("sharpe_proxy") or 0,
                confidence=profile.get("profile_confidence") or "LOW",
                is_priority=False,
            )
            best_score = max(best_score, score)

        db.update_scalper_pool_fields(
            titular["wallet_address"],
            {"composite_score": round(best_score, 4)},
            run_id=self.run_id,
        )
