"""
Portfolio-relative position sizing for Scalper V2.

Sizing is based on OUR portfolio, not on the titular's trade size.
Autocompounding: uses current_capital (not initial) so positions grow/shrink
with portfolio performance.

Each titular gets a base 25% allocation (1/num_titulars). A sustained winning
streak (≥3 consecutive wins) grants a temporary +5% bonus (max 30%).

When a titular's allocation is exhausted, the caller should open a shadow
trade instead of a real trade.
"""
from __future__ import annotations

from src.strategies.common import config as C, db
from src.utils.logger import logger


class PortfolioSizer:
    """Compute trade sizes relative to our portfolio allocation per titular."""

    def __init__(self, *, run_id: str, num_titulars: int = C.SCALPER_ACTIVE_WALLETS):
        self._run_id = run_id
        self._num_titulars = max(1, num_titulars)

    def compute_trade_size(self, titular_wallet: str) -> float:
        """Return the USD size for a new trade by this titular.

        Returns 0.0 if the titular's allocation is exhausted (caller should
        open as shadow trade).
        """
        portfolio = db.get_portfolio("SCALPER", run_id=self._run_id)
        if not portfolio:
            return 0.0
        current_capital = float(portfolio.get("current_capital") or 0)
        if current_capital <= 0:
            return 0.0

        # Base allocation: 25% per titular (autocompounding with current capital)
        base_pct = 1.0 / self._num_titulars

        # Bonus: +5% if titular has ≥3 consecutive wins
        titular_state = db.get_scalper_pool_entry(titular_wallet, run_id=self._run_id)
        consec_wins = int((titular_state or {}).get("consecutive_wins") or 0)
        if consec_wins >= 3:
            alloc_pct = min(base_pct + C.SCALPER_BONUS_PCT, 0.30)
        else:
            alloc_pct = base_pct

        titular_allocation = current_capital * alloc_pct

        # Current exposure for this titular
        open_trades = db.list_open_trades_for_titular(titular_wallet, run_id=self._run_id)
        current_exposure = sum(float(t.get("position_usd") or 0) for t in open_trades)
        remaining = titular_allocation - current_exposure

        if remaining <= C.SCALPER_MIN_PER_TRADE:
            return 0.0  # allocation exhausted

        trade_pct = C.SCALPER_TRADE_PCT
        max_pct = C.SCALPER_MAX_TRADE_PCT

        size = titular_allocation * trade_pct
        size = min(size, remaining)
        size = min(size, titular_allocation * max_pct)
        size = max(size, C.SCALPER_MIN_PER_TRADE)

        return round(size, 2)

    def get_titular_allocation(self, titular_wallet: str) -> dict:
        """Return allocation details for a titular (used by dashboard)."""
        portfolio = db.get_portfolio("SCALPER", run_id=self._run_id)
        current_capital = float((portfolio or {}).get("current_capital") or 0)
        base_pct = 1.0 / self._num_titulars

        titular_state = db.get_scalper_pool_entry(titular_wallet, run_id=self._run_id)
        consec_wins = int((titular_state or {}).get("consecutive_wins") or 0)
        alloc_pct = min(base_pct + C.SCALPER_BONUS_PCT, 0.30) if consec_wins >= 3 else base_pct
        allocation_usd = current_capital * alloc_pct

        open_trades = db.list_open_trades_for_titular(titular_wallet, run_id=self._run_id)
        exposure = sum(float(t.get("position_usd") or 0) for t in open_trades)

        return {
            "allocation_pct": round(alloc_pct, 4),
            "allocation_usd": round(allocation_usd, 2),
            "current_exposure_usd": round(exposure, 2),
            "remaining_usd": round(max(0, allocation_usd - exposure), 2),
            "open_positions": len(open_trades),
            "has_bonus": consec_wins >= 3,
            "consecutive_wins": consec_wins,
        }
