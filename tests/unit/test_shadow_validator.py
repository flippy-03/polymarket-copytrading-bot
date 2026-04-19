"""Tests for shadow_validator evaluator.

Covers the promote/reject decision logic using mocked DB responses.
"""
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from src.strategies.scalper import shadow_validator as sv
from src.strategies.common import config as C


def _fake_client_with_rows(pending_rows=None, paper_rows=None):
    """Build a mock supabase client that returns the given rows per
    .eq/.select/.execute() chain."""
    client = MagicMock()
    call_sequence = [
        pending_rows if pending_rows is not None else [],
        paper_rows if paper_rows is not None else [],
    ]
    idx = {"v": 0}

    def execute_side_effect(*a, **k):
        result = MagicMock()
        i = idx["v"]
        result.data = call_sequence[i] if i < len(call_sequence) else []
        idx["v"] = i + 1
        return result

    table = MagicMock()
    table.select.return_value = table
    table.update.return_value = table
    table.eq.return_value = table
    table.gte.return_value = table
    table.execute.side_effect = execute_side_effect
    client.table.return_value = table
    return client


class TestPromotion:

    def test_promotes_when_metrics_pass(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        pending = [{"wallet_address": "0xabc", "shadow_validation_until": past, "entered_at": past}]
        # 6 closed trades, 4 wins, $600 size, +$50 pnl → WR 67%, +8.3% ratio
        paper = [
            {"pnl_usd": 20.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": 15.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": 30.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": 10.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": -15.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": -10.0, "position_usd": 100.0, "status": "CLOSED"},
        ]
        with patch.object(sv._db, "get_client", return_value=_fake_client_with_rows(pending, paper)):
            summary = sv.evaluate("run-1")
        assert summary["promoted"] == 1
        assert summary["rejected"] == 0

    def test_rejects_when_too_few_trades(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        pending = [{"wallet_address": "0xabc", "shadow_validation_until": past, "entered_at": past}]
        # only 2 trades — below SHADOW_MIN_TRADES (5)
        paper = [
            {"pnl_usd": 10.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": 10.0, "position_usd": 100.0, "status": "CLOSED"},
        ]
        with patch.object(sv._db, "get_client", return_value=_fake_client_with_rows(pending, paper)):
            summary = sv.evaluate("run-1")
        assert summary["rejected"] == 1
        assert summary["promoted"] == 0

    def test_rejects_when_wr_too_low(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        pending = [{"wallet_address": "0xabc", "shadow_validation_until": past, "entered_at": past}]
        # 6 trades, only 2 wins → WR 33% < 55%
        paper = [
            {"pnl_usd": 10.0, "position_usd": 100.0, "status": "CLOSED"},
            {"pnl_usd": 10.0, "position_usd": 100.0, "status": "CLOSED"},
        ] + [
            {"pnl_usd": -5.0, "position_usd": 100.0, "status": "CLOSED"} for _ in range(4)
        ]
        with patch.object(sv._db, "get_client", return_value=_fake_client_with_rows(pending, paper)):
            summary = sv.evaluate("run-1")
        assert summary["rejected"] == 1

    def test_rejects_when_pnl_negative(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        pending = [{"wallet_address": "0xabc", "shadow_validation_until": past, "entered_at": past}]
        # 6 trades, 5 wins BUT pnl_ratio negative (small wins, huge loss)
        paper = [
            {"pnl_usd": 1.0, "position_usd": 100.0, "status": "CLOSED"} for _ in range(5)
        ] + [
            {"pnl_usd": -50.0, "position_usd": 100.0, "status": "CLOSED"},
        ]
        with patch.object(sv._db, "get_client", return_value=_fake_client_with_rows(pending, paper)):
            summary = sv.evaluate("run-1")
        assert summary["rejected"] == 1

    def test_skips_still_pending_window(self):
        future = (datetime.now(tz=timezone.utc) + timedelta(days=1)).isoformat()
        pending = [{"wallet_address": "0xabc", "shadow_validation_until": future, "entered_at": future}]
        with patch.object(sv._db, "get_client", return_value=_fake_client_with_rows(pending, [])):
            summary = sv.evaluate("run-1")
        assert summary["still_pending"] == 1
        assert summary["promoted"] == 0
        assert summary["rejected"] == 0
