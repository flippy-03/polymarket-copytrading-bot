"""
Scalper V2 Executor — mirror-opens and mirror-closes paper trades against
titular wallets' live activity.

Key V2 changes vs V1:
  - Sizing via PortfolioSizer (% of OUR portfolio, not titular's trade)
  - market_type classification and storage on every trade
  - Per-titular risk tracking (register_titular_loss on close)
  - Shadow trades when allocation exhausted or risk blocked
"""
from src.db import supabase_client as _db
from src.strategies.common import clob_exec, config as C, db
from src.strategies.common import risk_manager_ct as risk
from src.strategies.common.data_client import DataClient
from src.strategies.common.wallet_analyzer import _usdc
from src.strategies.scalper.portfolio_sizer import PortfolioSizer
from src.strategies.specialist.market_type_classifier import classify
from src.utils.logger import logger


class ScalperExecutor:
    STRATEGY = "SCALPER"

    def __init__(self, data: DataClient | None = None, *, run_id: str | None = None):
        self.data = data or DataClient()
        self._owns_data = data is None
        self.run_id = run_id or db.get_active_run(self.STRATEGY)
        self._sizer = PortfolioSizer(run_id=self.run_id)
        db.ensure_portfolio_row(
            self.STRATEGY, run_id=self.run_id, is_shadow=False,
            initial_capital=C.SCALPER_INITIAL_CAPITAL,
            max_open_positions=C.SCALPER_MAX_OPEN_POSITIONS,
        )
        db.ensure_portfolio_row(
            self.STRATEGY, run_id=self.run_id, is_shadow=True,
            initial_capital=C.SCALPER_INITIAL_CAPITAL,
            max_open_positions=C.SCALPER_MAX_OPEN_POSITIONS,
        )

    def close(self):
        if self._owns_data:
            self.data.close()

    # ── titular enrichment ───────────────────────────────

    def _get_titular_stats(self, titular: str, market_type: str) -> dict:
        """Fetch titular hit rate (for this market_type) and composite_score.

        Used to enrich trade metadata so the dashboard can display Avg HR / EV
        without additional queries. Errors swallowed — the metadata fields are
        rendered as "—" when absent.
        """
        out: dict = {}
        try:
            client = _db.get_client()
            prof = (
                client.table("wallet_profiles")
                .select("type_hit_rates")
                .eq("wallet", titular)
                .limit(1)
                .execute()
                .data
            )
            if prof:
                type_hrs = (prof[0] or {}).get("type_hit_rates") or {}
                hr = type_hrs.get(market_type)
                if hr is not None:
                    out["avg_hit_rate"] = float(hr)
            pool = (
                client.table("scalper_pool")
                .select("composite_score")
                .eq("run_id", self.run_id)
                .eq("wallet_address", titular)
                .limit(1)
                .execute()
                .data
            )
            if pool:
                cs = (pool[0] or {}).get("composite_score")
                if cs is not None:
                    out["composite_score"] = float(cs)
        except Exception as e:
            logger.debug(f"_get_titular_stats({titular[:10]}): {e}")
        return out

    def _get_approved_types(self, titular: str) -> set[str] | None:
        """Fetch the titular's approved_market_types from scalper_pool.

        Returns None if the lookup fails (allow-all fallback, we'd rather
        copy than silently drop trades if the DB hiccups). Returns a set
        otherwise — membership check in O(1) at call site.
        """
        try:
            client = _db.get_client()
            row = (
                client.table("scalper_pool")
                .select("approved_market_types")
                .eq("run_id", self.run_id)
                .eq("wallet_address", titular)
                .limit(1)
                .execute()
                .data
            )
            if row:
                approved = (row[0] or {}).get("approved_market_types") or []
                if isinstance(approved, list) and approved:
                    return set(approved)
        except Exception as e:
            logger.debug(f"_get_approved_types({titular[:10]}): {e}")
        return None

    def _is_in_shadow_window(self, titular: str) -> bool:
        """True if titular is still inside the shadow validation window.

        The shadow_validator job promotes/retires when the window expires;
        until then, this method keeps all trades as is_shadow=True.
        """
        try:
            client = _db.get_client()
            row = (
                client.table("scalper_pool")
                .select("shadow_validation_until,validation_outcome")
                .eq("run_id", self.run_id)
                .eq("wallet_address", titular)
                .limit(1)
                .execute()
                .data
            )
            if not row:
                return False
            r = row[0] or {}
            until = r.get("shadow_validation_until")
            outcome = r.get("validation_outcome")
            if outcome == "PROMOTED":
                return False
            if outcome == "REJECTED":
                # Still in shadow/retired — skipping is caller's job
                return True
            if not until:
                return False
            from datetime import datetime, timezone
            deadline = datetime.fromisoformat(until.replace("Z", "+00:00"))
            return datetime.now(tz=timezone.utc) < deadline
        except Exception as e:
            logger.debug(f"_is_in_shadow_window({titular[:10]}): {e}")
            return False

    # ── open ─────────────────────────────────────────────

    def mirror_open(
        self,
        titular: str,
        trade: dict,
        *,
        force_shadow: bool = False,
        shadow_reason: str | None = None,
    ) -> dict | None:
        """Mirror a BUY trade from a titular.

        Args:
            force_shadow: If True, open as shadow regardless of risk checks.
            shadow_reason: Metadata reason when forced to shadow.

        Returns:
            Result dict from open_paper_trade, or None if skipped.
        """
        cid = trade.get("conditionId")
        asset = trade.get("asset")
        if not cid or not asset:
            return None

        outcome = (trade.get("outcome") or "").strip()
        direction = "YES" if outcome.lower().startswith("y") else "NO"
        market_type = classify(trade)

        # v3.1: event-level dedup. Polymarket data-api trade activity exposes
        # eventSlug directly at the top level. An event can contain multiple
        # markets (money-line, O/U, spread) — copying 2 titulars who bet the
        # same side of the same event duplicates correlated exposure for zero
        # diversification benefit. Bug detected in v3.0 Magic vs Pistons
        # (−$75 on 2 duplicated trades).
        event_slug = trade.get("eventSlug") or trade.get("event_slug")
        if not event_slug:
            evs = trade.get("events") or []
            if isinstance(evs, list) and evs and isinstance(evs[0], dict):
                event_slug = evs[0].get("slug")

        # v3.0: hard-block market types known to destroy edge in copy-trading
        # (micro-timeframe crypto, unclassified). Force shadow so we still
        # observe the decision but don't risk real capital.
        if market_type in C.SCALPER_BLOCKED_MARKET_TYPES:
            force_shadow = True
            shadow_reason = shadow_reason or f"blocked_type:{market_type}"

        # v3.0: also block if the titular's approved_market_types (from pool
        # selector) doesn't include this type. Titulars are selected based on
        # their edge in specific market types — copying them outside those
        # types has no justification.
        approved = self._get_approved_types(titular)
        if approved is not None and market_type not in approved:
            force_shadow = True
            shadow_reason = shadow_reason or f"type_not_approved:{market_type}"

        # v3.1: shadow validation gate — new titulars spend N days shadow-only.
        # Until the validator job promotes them, every trade is paper.
        if self._is_in_shadow_window(titular):
            force_shadow = True
            shadow_reason = shadow_reason or "shadow_validation_window"

        # Compute portfolio-relative size
        size_usd = self._sizer.compute_trade_size(titular)

        # If allocation exhausted, force shadow
        if size_usd <= 0:
            force_shadow = True
            shadow_reason = shadow_reason or "allocation_exhausted"

        if size_usd <= 0:
            # Use a nominal size for shadow trades
            size_usd = 50.0

        # Dedupe layer 1: skip if already OPEN real trade for same (titular, asset)
        if not force_shadow:
            client = _db.get_client()
            existing = (
                client.table("copy_trades")
                .select("id")
                .eq("run_id", self.run_id)
                .eq("strategy", self.STRATEGY)
                .eq("status", "OPEN")
                .eq("is_shadow", False)
                .eq("source_wallet", titular)
                .eq("outcome_token_id", asset)
                .limit(1)
                .execute()
                .data
            )
            if existing:
                return None

        # v3.1 Dedupe layer 2: event-level correlation check. If ANOTHER
        # titular already has an OPEN real trade on the same event and the
        # same direction, downgrade this one to shadow. Keeps the observation
        # (shadow trade gets opened) but removes the duplicate real exposure.
        # Two titulars disagreeing (YES vs NO) are allowed — they hedge.
        if not force_shadow and event_slug:
            existing_event = (
                client.table("copy_trades")
                .select("id,source_wallet,metadata,direction")
                .eq("run_id", self.run_id)
                .eq("strategy", self.STRATEGY)
                .eq("status", "OPEN")
                .eq("is_shadow", False)
                .eq("direction", direction)
                .execute()
                .data
            ) or []
            for other in existing_event:
                other_meta = other.get("metadata") or {}
                if other_meta.get("event_slug") == event_slug:
                    force_shadow = True
                    shadow_reason = shadow_reason or (
                        f"event_already_copied:{event_slug[:30]}"
                    )
                    break

        # Enrich metadata with titular-level KPIs so dashboard can show
        # Avg HR, EV, composite score per trade without joins.
        stats = self._get_titular_stats(titular, market_type)

        metadata = {
            "titular": titular,
            "titular_usdc": _usdc(trade),
            "titular_price": float(trade.get("price") or 0),
            "market_type": market_type,
            "event_slug": event_slug,    # v3.1 — for cross-titular event dedup
            "avg_hit_rate": stats.get("avg_hit_rate"),
            "composite_score": stats.get("composite_score"),
            "closes_at": (
                trade.get("gameStartTime")
                or trade.get("endDate")
                or trade.get("endDateIso")
            ),
        }
        if force_shadow and shadow_reason:
            metadata["filter_reason"] = shadow_reason

        return clob_exec.open_paper_trade(
            strategy=self.STRATEGY,
            market_polymarket_id=cid,
            outcome_token_id=asset,
            direction=direction,
            size_usd=round(size_usd, 2),
            run_id=self.run_id,
            source_wallet=titular,
            market_question=trade.get("title") or trade.get("question"),
            market_category=market_type,
            metadata=metadata,
            force_shadow=force_shadow,
        )

    # ── close ────────────────────────────────────────────

    def mirror_close(self, titular: str, trade: dict) -> int:
        """Close all open trades for a titular + asset when they SELL."""
        asset = trade.get("asset")
        if not asset:
            return 0
        client = _db.get_client()

        # Close real trades
        real_rows = (
            client.table("copy_trades")
            .select("id")
            .eq("run_id", self.run_id)
            .eq("strategy", self.STRATEGY)
            .eq("status", "OPEN")
            .eq("is_shadow", False)
            .eq("source_wallet", titular)
            .eq("outcome_token_id", asset)
            .execute()
            .data
        )
        for r in real_rows:
            clob_exec.close_paper_trade(r["id"], reason="SCALPER_TITULAR_EXIT")

        # Close shadow trades (pure side)
        shadow_rows = (
            client.table("copy_trades")
            .select("id")
            .eq("run_id", self.run_id)
            .eq("strategy", self.STRATEGY)
            .eq("status", "OPEN")
            .eq("is_shadow", True)
            .eq("source_wallet", titular)
            .eq("outcome_token_id", asset)
            .execute()
            .data
        )
        for r in shadow_rows:
            clob_exec.close_shadow_trade(r["id"], reason="SCALPER_TITULAR_EXIT")

        return len(real_rows) + len(shadow_rows)

    # ── tick-level shadow stops ──────────────────────────

    def evaluate_shadow_stops(self) -> int:
        return clob_exec.evaluate_shadow_stops(self.STRATEGY, run_id=self.run_id)
