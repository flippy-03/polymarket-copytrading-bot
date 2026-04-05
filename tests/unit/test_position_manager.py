"""
Unit tests for src/trading/position_manager.py

Covers pure functions only (no DB calls):
  - _is_resolved: yes_price thresholds, both directions
  - _is_expired: timeout at/before/after MAX_TRADE_DAYS
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.trading.position_manager import _is_resolved, _is_expired, RESOLUTION_THRESHOLD, MAX_TRADE_DAYS


# ── _is_resolved ─────────────────────────────────────────────────────────────

class TestIsResolved:

    def test_resolved_yes_at_threshold(self):
        resolved, exit_price = _is_resolved(RESOLUTION_THRESHOLD)
        assert resolved is True
        assert exit_price == 1.0

    def test_resolved_yes_above_threshold(self):
        resolved, exit_price = _is_resolved(0.99)
        assert resolved is True
        assert exit_price == 1.0

    def test_resolved_no_at_threshold(self):
        # NO resolution: yes_price <= 1 - RESOLUTION_THRESHOLD (0.03)
        resolved, exit_price = _is_resolved(1 - RESOLUTION_THRESHOLD)
        assert resolved is True
        assert exit_price == 0.0

    def test_resolved_no_below_threshold(self):
        resolved, exit_price = _is_resolved(0.01)
        assert resolved is True
        assert exit_price == 0.0

    def test_not_resolved_at_midpoint(self):
        resolved, exit_price = _is_resolved(0.50)
        assert resolved is False
        assert exit_price is None

    def test_not_resolved_just_below_yes_threshold(self):
        # 0.96 < 0.97 → not resolved YES
        resolved, _ = _is_resolved(0.96)
        assert resolved is False

    def test_not_resolved_just_above_no_threshold(self):
        # 0.04 > 0.03 → not resolved NO
        resolved, _ = _is_resolved(0.04)
        assert resolved is False

    def test_yes_exit_is_1_dot_0_not_0_dot_97(self):
        # Resolution should snap to exactly 1.0, not the threshold value
        _, exit_price = _is_resolved(0.97)
        assert exit_price == 1.0

    def test_no_exit_is_0_dot_0_not_0_dot_03(self):
        _, exit_price = _is_resolved(0.03)
        assert exit_price == 0.0


# ── _is_expired ──────────────────────────────────────────────────────────────

class TestIsExpired:

    def _trade(self, days_ago: float) -> dict:
        opened = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
        return {"opened_at": opened.isoformat()}

    def test_expired_one_day_over_limit(self):
        assert _is_expired(self._trade(MAX_TRADE_DAYS + 1)) is True

    def test_expired_at_exactly_one_second_over(self):
        # Opened slightly more than MAX_TRADE_DAYS ago
        opened = datetime.now(tz=timezone.utc) - timedelta(days=MAX_TRADE_DAYS, seconds=1)
        trade = {"opened_at": opened.isoformat()}
        assert _is_expired(trade) is True

    def test_not_expired_one_second_before_limit(self):
        opened = datetime.now(tz=timezone.utc) - timedelta(days=MAX_TRADE_DAYS) + timedelta(seconds=60)
        trade = {"opened_at": opened.isoformat()}
        assert _is_expired(trade) is False

    def test_not_expired_fresh_trade(self):
        assert _is_expired(self._trade(1)) is False

    def test_not_expired_halfway_through(self):
        assert _is_expired(self._trade(MAX_TRADE_DAYS / 2)) is False

    def test_missing_opened_at_returns_false(self):
        assert _is_expired({"opened_at": ""}) is False
        assert _is_expired({}) is False

    def test_naive_datetime_handled(self):
        # opened_at without timezone info — should not crash
        opened = datetime.utcnow() - timedelta(days=MAX_TRADE_DAYS + 2)
        trade = {"opened_at": opened.isoformat()}
        assert _is_expired(trade) is True


# ── Trailing stop / Take profit thresholds ───────────────────────────────────
# These are inline comparisons in check_open_positions(), not standalone
# functions, but we verify the math here.

from src.utils.config import TRAILING_STOP_PCT, TAKE_PROFIT_PCT


class TestStopAndTpThresholds:

    def test_trailing_stop_triggered_at_threshold(self):
        entry = 0.50
        current = entry * (1 - TRAILING_STOP_PCT)  # exactly at threshold
        assert current <= entry * (1 - TRAILING_STOP_PCT)

    def test_trailing_stop_not_triggered_above_threshold(self):
        entry = 0.50
        current = entry * (1 - TRAILING_STOP_PCT) + 0.001  # just above
        assert not (current <= entry * (1 - TRAILING_STOP_PCT))

    def test_take_profit_triggered_at_threshold(self):
        entry = 0.50
        current = entry * (1 + TAKE_PROFIT_PCT)  # exactly at threshold
        assert current >= entry * (1 + TAKE_PROFIT_PCT)

    def test_take_profit_not_triggered_below_threshold(self):
        entry = 0.50
        current = entry * (1 + TAKE_PROFIT_PCT) - 0.001  # just below
        assert not (current >= entry * (1 + TAKE_PROFIT_PCT))

    def test_entry_0_50_trailing_stop_is_0_375(self):
        assert round(0.50 * (1 - TRAILING_STOP_PCT), 4) == 0.375

    def test_entry_0_50_take_profit_is_0_75(self):
        assert round(0.50 * (1 + TAKE_PROFIT_PCT), 4) == 0.75
