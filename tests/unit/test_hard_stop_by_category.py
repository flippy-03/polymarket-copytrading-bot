"""Tests for the category-aware hard-stop in scalper.copy_monitor.

The rule:
  - sports_winner / sports_spread / sports_total / sports_futures → −0.40
  - anything else (crypto_above, financial_*, unknown, None) → −0.20

The full close-trade path goes through DB, so we unit-test the pure
helper _hard_stop_for. The integration (calls clob_exec.close_paper_trade
only when trailing is inactive and pct_change crosses the threshold)
is verified by reading the updated copy_monitor._evaluate_trailing_stops.
"""
from src.strategies.scalper.copy_monitor import _hard_stop_for
from src.strategies.common import config as C


class TestHardStopByCategory:

    def test_sports_winner_uses_wider_stop(self):
        assert _hard_stop_for("sports_winner") == C.SPORTS_HARD_STOP_PCT
        assert _hard_stop_for("sports_winner") == -0.40

    def test_sports_spread_uses_wider_stop(self):
        assert _hard_stop_for("sports_spread") == -0.40

    def test_sports_total_uses_wider_stop(self):
        assert _hard_stop_for("sports_total") == -0.40

    def test_sports_futures_uses_wider_stop(self):
        assert _hard_stop_for("sports_futures") == -0.40

    def test_crypto_above_uses_default_stop(self):
        assert _hard_stop_for("crypto_above") == C.TS_HARD_STOP
        assert _hard_stop_for("crypto_above") == -0.20

    def test_crypto_below_uses_default_stop(self):
        assert _hard_stop_for("crypto_below") == -0.20

    def test_financial_index_uses_default_stop(self):
        assert _hard_stop_for("financial_index") == -0.20

    def test_none_category_uses_default_stop(self):
        assert _hard_stop_for(None) == -0.20

    def test_unclassified_uses_default_stop(self):
        assert _hard_stop_for("unclassified") == -0.20

    def test_magic_vs_pistons_scenario(self):
        """Entry 0.78 NO, sports_winner → hard stop at 0.78 * 0.60 = 0.468."""
        entry = 0.78
        hs = _hard_stop_for("sports_winner")
        threshold_price = round(entry * (1 + hs), 3)
        assert threshold_price == 0.468

    def test_btc_updown_scenario(self):
        """Entry 0.50 on a crypto_above, stop at 0.50 * 0.80 = 0.40."""
        entry = 0.50
        hs = _hard_stop_for("crypto_above")
        threshold_price = round(entry * (1 + hs), 3)
        assert threshold_price == 0.40
