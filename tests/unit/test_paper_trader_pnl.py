"""
Unit tests for P&L calculation logic in src/trading/paper_trader.py

close_trade() computes:
  pnl_usd = round((exit_price - entry_price) * shares, 2)
  pnl_pct  = round(pnl_usd / position_usd, 4)

Both YES and NO trades use the same formula — entry_price for NO trades is
already converted to the NO perspective (1 - yes_price) at open time.

We test the math directly without touching the DB.
"""
import pytest
import math


def _calc_pnl(entry: float, exit_p: float, shares: float, position_usd: float):
    """Exact formula from paper_trader.close_trade()."""
    pnl_usd = round((exit_p - entry) * shares, 2)
    pnl_pct = round(pnl_usd / position_usd, 4) if position_usd > 0 else 0
    return pnl_usd, pnl_pct


# ── YES trades ────────────────────────────────────────────────────────────────

class TestYesTradePnl:

    def test_yes_win_resolution(self):
        # Bought YES at 0.50, market resolves YES → exit at 1.00
        # shares = $20 / 0.50 = 40
        pnl, pct = _calc_pnl(entry=0.50, exit_p=1.00, shares=40.0, position_usd=20.0)
        assert pnl == 20.0   # (1.00 - 0.50) * 40
        assert pct == 1.0    # 100% return

    def test_yes_loss_resolution(self):
        # Bought YES at 0.50, market resolves NO → exit at 0.00
        pnl, pct = _calc_pnl(entry=0.50, exit_p=0.00, shares=40.0, position_usd=20.0)
        assert pnl == -20.0
        assert pct == -1.0

    def test_yes_win_take_profit(self):
        # Entry 0.50, TP at entry * 1.50 = 0.75, shares=40
        pnl, pct = _calc_pnl(entry=0.50, exit_p=0.75, shares=40.0, position_usd=20.0)
        assert pnl == 10.0   # (0.75 - 0.50) * 40
        assert pct == 0.50   # 50% return

    def test_yes_loss_trailing_stop(self):
        # Entry 0.50, stop at entry * 0.75 = 0.375, shares=40
        pnl, pct = _calc_pnl(entry=0.50, exit_p=0.375, shares=40.0, position_usd=20.0)
        assert pnl == -5.0   # (0.375 - 0.50) * 40
        assert pct == -0.25  # -25%


# ── NO trades ─────────────────────────────────────────────────────────────────

class TestNoTradePnl:

    def test_no_win_resolution(self):
        # YES was at 0.70 → NO entry = 0.30, market resolves NO → yes_price=0.00
        # exit for NO = 1 - 0.00 = 1.00 (full payout)
        # shares = $15 / 0.30 = 50
        pnl, pct = _calc_pnl(entry=0.30, exit_p=1.00, shares=50.0, position_usd=15.0)
        assert pnl == 35.0   # (1.00 - 0.30) * 50
        assert pct == round(35 / 15, 4)

    def test_no_loss_resolution(self):
        # YES at 0.70 → NO entry = 0.30, market resolves YES → yes_price=1.00
        # exit for NO = 1 - 1.00 = 0.00 (full loss)
        pnl, pct = _calc_pnl(entry=0.30, exit_p=0.00, shares=50.0, position_usd=15.0)
        assert pnl == -15.0
        assert pct == -1.0

    def test_no_win_take_profit(self):
        # Entry 0.30, TP = 0.30 * 1.50 = 0.45, shares=50
        pnl, pct = _calc_pnl(entry=0.30, exit_p=0.45, shares=50.0, position_usd=15.0)
        assert pnl == 7.5    # (0.45 - 0.30) * 50
        assert pct == 0.50   # 50%

    def test_no_loss_trailing_stop(self):
        # Entry 0.30, stop = 0.30 * 0.75 = 0.225, shares=50
        pnl, pct = _calc_pnl(entry=0.30, exit_p=0.225, shares=50.0, position_usd=15.0)
        assert pnl == -3.75  # (0.225 - 0.30) * 50
        assert pct == -0.25  # -25%


# ── P&L properties ───────────────────────────────────────────────────────────

class TestPnlProperties:

    def test_breakeven_exit_gives_zero_pnl(self):
        pnl, pct = _calc_pnl(entry=0.50, exit_p=0.50, shares=20.0, position_usd=10.0)
        assert pnl == 0.0
        assert pct == 0.0

    def test_pnl_is_positive_when_exit_above_entry(self):
        pnl, _ = _calc_pnl(entry=0.40, exit_p=0.60, shares=25.0, position_usd=10.0)
        assert pnl > 0

    def test_pnl_is_negative_when_exit_below_entry(self):
        pnl, _ = _calc_pnl(entry=0.60, exit_p=0.40, shares=25.0, position_usd=15.0)
        assert pnl < 0

    def test_max_loss_is_position_usd(self):
        # Exit at 0 → total loss = entry * shares = position_usd
        entry = 0.40
        shares = 25.0
        position_usd = entry * shares  # 10.0
        pnl, pct = _calc_pnl(entry=entry, exit_p=0.0, shares=shares, position_usd=position_usd)
        assert pnl == -position_usd
        assert pct == -1.0

    def test_pct_is_pnl_over_position_usd(self):
        entry, exit_p, shares, pos = 0.50, 0.65, 20.0, 10.0
        pnl, pct = _calc_pnl(entry, exit_p, shares, pos)
        assert pct == round(pnl / pos, 4)

    def test_rounding_two_decimal_places(self):
        # Ensure pnl_usd is rounded to 2 decimal places
        pnl, _ = _calc_pnl(entry=0.333, exit_p=0.667, shares=30.0, position_usd=9.99)
        assert pnl == round((0.667 - 0.333) * 30, 2)
