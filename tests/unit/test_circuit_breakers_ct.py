"""Tests for risk_manager_ct per-titular circuit breaker.

v2.1 postmortem found `register_titular_loss` was defined but never invoked.
These tests verify:
  1. The function increments correctly.
  2. Wins reset the streak.
  3. Reaching the limit sets per_trader_is_broken=True.
  4. is_titular_broken() reflects the stored state.
"""
from unittest.mock import patch

from src.strategies.common import risk_manager_ct as risk


RUN_ID = "test-run-v3"
WALLET = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _fake_entry(**overrides) -> dict:
    base = {
        "wallet_address": WALLET,
        "run_id": RUN_ID,
        "per_trader_consecutive_losses": 0,
        "per_trader_loss_limit": 4,
        "per_trader_is_broken": False,
        "consecutive_wins": 0,
    }
    base.update(overrides)
    return base


class TestRegisterTitularLoss:

    def test_loss_increments_streak(self):
        entry = _fake_entry()
        captured = {}
        def fake_update(wallet, data, *, run_id):
            captured.update(data)
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=entry), \
             patch.object(risk.db, "update_scalper_pool_fields", side_effect=fake_update):
            risk.register_titular_loss(WALLET, -0.20, run_id=RUN_ID)
        assert captured.get("per_trader_consecutive_losses") == 1
        assert captured.get("consecutive_wins") == 0
        assert captured.get("per_trader_is_broken") is not True

    def test_win_resets_streak_and_increments_wins(self):
        entry = _fake_entry(per_trader_consecutive_losses=2, consecutive_wins=0)
        captured = {}
        def fake_update(wallet, data, *, run_id):
            captured.update(data)
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=entry), \
             patch.object(risk.db, "update_scalper_pool_fields", side_effect=fake_update):
            risk.register_titular_loss(WALLET, +0.10, run_id=RUN_ID)
        assert captured.get("per_trader_consecutive_losses") == 0
        assert captured.get("consecutive_wins") == 1

    def test_scratch_does_not_increment_streak(self):
        # pnl_pct = -0.01 → scratch (> -0.02), treated as win-equivalent
        entry = _fake_entry(per_trader_consecutive_losses=1)
        captured = {}
        def fake_update(wallet, data, *, run_id):
            captured.update(data)
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=entry), \
             patch.object(risk.db, "update_scalper_pool_fields", side_effect=fake_update):
            risk.register_titular_loss(WALLET, -0.01, run_id=RUN_ID)
        assert captured.get("per_trader_consecutive_losses") == 0

    def test_breaks_titular_at_limit(self):
        # Already 3 losses, limit=4, one more loss → break
        entry = _fake_entry(per_trader_consecutive_losses=3, per_trader_loss_limit=4)
        captured = {}
        def fake_update(wallet, data, *, run_id):
            captured.update(data)
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=entry), \
             patch.object(risk.db, "update_scalper_pool_fields", side_effect=fake_update):
            risk.register_titular_loss(WALLET, -0.15, run_id=RUN_ID)
        assert captured.get("per_trader_consecutive_losses") == 4
        assert captured.get("per_trader_is_broken") is True

    def test_noop_when_entry_missing(self):
        """If the wallet isn't in scalper_pool, silently return."""
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=None), \
             patch.object(risk.db, "update_scalper_pool_fields") as upd:
            risk.register_titular_loss(WALLET, -0.50, run_id=RUN_ID)
            upd.assert_not_called()


class TestIsTitularBroken:

    def test_returns_true_when_broken(self):
        with patch.object(
            risk.db, "get_scalper_pool_entry",
            return_value=_fake_entry(per_trader_is_broken=True),
        ):
            assert risk.is_titular_broken(WALLET, run_id=RUN_ID) is True

    def test_returns_false_when_healthy(self):
        with patch.object(
            risk.db, "get_scalper_pool_entry",
            return_value=_fake_entry(per_trader_is_broken=False),
        ):
            assert risk.is_titular_broken(WALLET, run_id=RUN_ID) is False

    def test_returns_false_when_no_entry(self):
        with patch.object(risk.db, "get_scalper_pool_entry", return_value=None):
            assert risk.is_titular_broken(WALLET, run_id=RUN_ID) is False


class TestResetTitularStreak:

    def test_resets_both_counter_and_flag(self):
        captured = {}
        def fake_update(wallet, data, *, run_id):
            captured.update(data)
        with patch.object(risk.db, "update_scalper_pool_fields", side_effect=fake_update):
            risk.reset_titular_streak(WALLET, run_id=RUN_ID)
        assert captured.get("per_trader_consecutive_losses") == 0
        assert captured.get("per_trader_is_broken") is False
