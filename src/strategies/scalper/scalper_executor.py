"""
Scalper Executor — mirror-opens and mirror-closes paper trades against the
titular wallets' live activity. Sizing is 5-10% of the titular trade, clamped
to [SCALPER_MIN_PER_TRADE, SCALPER_MAX_PER_TRADE] and bounded by the strategy
capital share assigned to that titular.
"""
from src.db import supabase_client as _db
from src.strategies.common import clob_exec, config as C, db
from src.strategies.common.data_client import DataClient
from src.utils.logger import logger


class ScalperExecutor:
    STRATEGY = "SCALPER"

    def __init__(self, data: DataClient | None = None):
        self.data = data or DataClient()
        self._owns_data = data is None

    def close(self):
        if self._owns_data:
            self.data.close()

    # ── sizing ───────────────────────────────────────────

    def _copy_size(self, titular_usdc: float) -> float:
        ratio = (C.SCALPER_COPY_RATIO_MIN + C.SCALPER_COPY_RATIO_MAX) / 2
        raw = titular_usdc * ratio
        return max(C.SCALPER_MIN_PER_TRADE, min(raw, C.SCALPER_MAX_PER_TRADE))

    # ── open ─────────────────────────────────────────────

    def mirror_open(self, titular: str, trade: dict) -> str | None:
        cid = trade.get("conditionId")
        asset = trade.get("asset")
        if not cid or not asset:
            return None

        outcome = (trade.get("outcome") or "").strip()
        direction = "YES" if outcome.lower().startswith("y") else "NO"
        titular_usdc = float(trade.get("usdcSize") or 0)
        size_usd = round(self._copy_size(titular_usdc), 2)
        if size_usd < C.SCALPER_MIN_PER_TRADE:
            return None

        # Dedupe: don't open a second position for the same (titular, asset) if already OPEN.
        client = _db.get_client()
        existing = (
            client.table("copy_trades")
            .select("id")
            .eq("strategy", self.STRATEGY)
            .eq("status", "OPEN")
            .eq("source_wallet", titular)
            .eq("outcome_token_id", asset)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            return None

        return clob_exec.open_paper_trade(
            strategy=self.STRATEGY,
            market_polymarket_id=cid,
            outcome_token_id=asset,
            direction=direction,
            size_usd=size_usd,
            source_wallet=titular,
            market_question=trade.get("title") or trade.get("question"),
            market_category=None,
            metadata={
                "titular": titular,
                "titular_usdc": titular_usdc,
                "titular_price": float(trade.get("price") or 0),
            },
        )

    # ── close ────────────────────────────────────────────

    def mirror_close(self, titular: str, trade: dict) -> int:
        asset = trade.get("asset")
        if not asset:
            return 0
        client = _db.get_client()
        rows = (
            client.table("copy_trades")
            .select("id")
            .eq("strategy", self.STRATEGY)
            .eq("status", "OPEN")
            .eq("source_wallet", titular)
            .eq("outcome_token_id", asset)
            .execute()
            .data
        )
        for r in rows:
            clob_exec.close_paper_trade(r["id"], reason="SCALPER_TITULAR_EXIT")
        return len(rows)
