"""
Unit tests for src/trading/risk_manager.py

Covers:
  - kelly_position_size: edge cases, cap at MAX_POSITION_SIZE_PCT
  - is_trading_allowed: circuit breaker (active/expired), drawdown, max positions, ok
"""
import pytest
from datetime import datetime, timezone, timedelta

from src.trading.risk_manager import kelly_position_size, is_trading_allowed
from src.utils.config import MAX_OPEN_POSITIONS, MAX_DRAWDOWN_PCT, MAX_POSITION_SIZE_PCT


# ── kelly_position_size ──────────────────────────────────────────────────────

class TestKellyPositionSize:

    def test_zero_edge_returns_zero(self):
        assert kelly_position_size(edge=0.0, odds=1.0, capital=1000) == 0.0

    def test_negative_edge_returns_zero(self):
        # edge=0.3, odds=1: kelly = (0.3 - 0.7) / 1 = -0.40 → 0
        assert kelly_position_size(edge=0.3, odds=1.0, capital=1000) == 0.0

    def test_zero_odds_returns_zero(self):
        assert kelly_position_size(edge=0.6, odds=0.0, capital=1000) == 0.0

    def test_negative_odds_returns_zero(self):
        assert kelly_position_size(edge=0.6, odds=-1.0, capital=1000) == 0.0

    def test_normal_sizing(self):
        # edge=0.55, odds=1.0 (entry=0.50): kelly_full = (0.55 - 0.45)/1 = 0.10
        # kelly_half = 0.05, raw = $50, max_size = $50 → $50.00
        result = kelly_position_size(edge=0.55, odds=1.0, capital=1000)
        assert result == 50.0

    def test_capped_at_max_position_pct(self):
        # Very high edge + high odds → kelly would suggest huge position
        # e.g. entry=0.10 → odds=9, edge=0.9: kelly_full = (0.9*9 - 0.1)/9 ≈ 0.889
        # kelly_half ≈ 0.444, raw = $444, max = $50 → capped at $50
        result = kelly_position_size(edge=0.9, odds=9.0, capital=1000)
        assert result == 1000 * MAX_POSITION_SIZE_PCT

    def test_position_scales_with_capital(self):
        r1 = kelly_position_size(edge=0.55, odds=1.0, capital=1000)
        r2 = kelly_position_size(edge=0.55, odds=1.0, capital=2000)
        assert r2 == r1 * 2

    def test_small_edge_returns_small_position(self):
        # edge=0.51 (tiny edge), odds=1.0: kelly_full = (0.51-0.49)/1 = 0.02
        # kelly_half = 0.01, raw = $10 → $10
        result = kelly_position_size(edge=0.51, odds=1.0, capital=1000)
        assert 0 < result < 1000 * MAX_POSITION_SIZE_PCT


# ── is_trading_allowed ───────────────────────────────────────────────────────

def _base_state(**overrides) -> dict:
    """Healthy portfolio state. Override specific fields for each test."""
    state = {
        "is_circuit_broken": False,
        "circuit_broken_until": None,
        "open_positions": 0,
        "current_capital": 1000.0,
        "initial_capital": 1000.0,
    }
    state.update(overrides)
    return state


class TestIsTradingAllowed:

    def test_ok_when_all_clear(self):
        allowed, reason = is_trading_allowed(_base_state())
        assert allowed is True
        assert reason == "ok"

    def test_blocked_by_active_circuit_breaker(self):
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
        state = _base_state(is_circuit_broken=True, circuit_broken_until=future)
        allowed, reason = is_trading_allowed(state)
        assert allowed is False
        assert "circuit_breaker" in reason

    def test_allowed_when_circuit_breaker_expired(self):
        # circuit_broken_until is in the past → CB has expired
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        state = _base_state(is_circuit_broken=True, circuit_broken_until=past)
        allowed, _ = is_trading_allowed(state)
        assert allowed is True

    def test_blocked_by_max_drawdown_exactly_at_limit(self):
        # current_capital = 800 → drawdown = 20% = MAX_DRAWDOWN_PCT
        state = _base_state(current_capital=1000 * (1 - MAX_DRAWDOWN_PCT))
        allowed, reason = is_trading_allowed(state)
        assert allowed is False
        assert "max_drawdown" in reason

    def test_blocked_by_max_drawdown_above_limit(self):
        state = _base_state(current_capital=750.0)  # 25% drawdown
        allowed, reason = is_trading_allowed(state)
        assert allowed is False
        assert "max_drawdown" in reason

    def test_allowed_just_below_drawdown_limit(self):
        # 19.9% drawdown — just inside limit
        state = _base_state(current_capital=801.0)
        allowed, _ = is_trading_allowed(state)
        assert allowed is True

    def test_blocked_by_max_open_positions(self):
        state = _base_state(open_positions=MAX_OPEN_POSITIONS)
        allowed, reason = is_trading_allowed(state)
        assert allowed is False
        assert "max_open_positions" in reason

    def test_allowed_one_below_max_positions(self):
        state = _base_state(open_positions=MAX_OPEN_POSITIONS - 1)
        allowed, _ = is_trading_allowed(state)
        assert allowed is True

    def test_circuit_breaker_takes_priority_over_drawdown(self):
        # Both CB and DD breached — reason should mention circuit_breaker (checked first)
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
        state = _base_state(
            is_circuit_broken=True,
            circuit_broken_until=future,
            current_capital=750.0,  # also over drawdown limit
        )
        allowed, reason = is_trading_allowed(state)
        assert allowed is False
        assert "circuit_breaker" in reason
