"""Tests for the force_shadow propagation fix.

Bug found 2026-04-20: scalper_executor.mirror_open correctly computed
force_shadow=True for titular_broken / event_already_copied / blocked_type
cases, but never passed it to clob_exec.open_paper_trade. As a result the
real trade opened anyway (subject only to the global CB, which didn't know
about per-titular state). Detroit Tigers trades opened at 12:51 and 13:23
from 0x146703a8 even though that titular was marked per_trader_is_broken=True
at 02:20.

Fix: open_paper_trade accepts force_shadow: bool = False; when True, the
real branch is skipped and only the shadow opens. scalper_executor now
passes force_shadow=force_shadow through.
"""
import inspect
from unittest.mock import patch, MagicMock

from src.strategies.common import clob_exec


class TestOpenPaperTradeSignature:
    """The signature must accept force_shadow as a keyword argument."""

    def test_force_shadow_in_signature(self):
        sig = inspect.signature(clob_exec.open_paper_trade)
        assert "force_shadow" in sig.parameters
        assert sig.parameters["force_shadow"].default is False

    def test_force_shadow_default_is_false(self):
        """SPECIALIST never passes force_shadow; default must be False so
        legacy callers still get the real branch under normal risk gating."""
        sig = inspect.signature(clob_exec.open_paper_trade)
        assert sig.parameters["force_shadow"].default is False


class TestForceShadowBehaviour:

    def _patch_common(self, price=0.50):
        """Patch the boundaries of open_paper_trade so we can observe which
        internal helpers it calls without touching the DB."""
        patches = [
            patch.object(clob_exec, "get_token_price", return_value=price),
            patch.object(clob_exec, "_record_price"),
            patch.object(clob_exec, "_open_row", return_value="fake-id"),
            patch.object(clob_exec, "_increment_open_positions"),
        ]
        mocks = [p.start() for p in patches]
        return patches, mocks

    def _unpatch(self, patches):
        for p in patches:
            p.stop()

    def test_force_shadow_true_skips_real_branch(self):
        patches, (m_price, m_record, m_open_row, m_inc) = self._patch_common()
        # We also patch risk.can_open_position to ensure it's NOT consulted.
        with patch.object(clob_exec.risk, "can_open_position") as risk_mock:
            risk_mock.return_value = (True, "ok")   # even if available, don't use
            try:
                clob_exec.open_paper_trade(
                    strategy="SCALPER",
                    market_polymarket_id="cid",
                    outcome_token_id="asset",
                    direction="NO",
                    size_usd=40.0,
                    run_id="run-x",
                    force_shadow=True,
                )
            finally:
                self._unpatch(patches)
            # risk.can_open_position must not be consulted when force_shadow is set.
            risk_mock.assert_not_called()
        # _open_row is called once for the shadow; never for a real when
        # force_shadow=True.
        assert m_open_row.call_count == 1
        # the call must have is_shadow=True
        kwargs = m_open_row.call_args.kwargs
        assert kwargs["is_shadow"] is True

    def test_force_shadow_false_preserves_legacy_behaviour(self):
        patches, (m_price, m_record, m_open_row, m_inc) = self._patch_common()
        with patch.object(clob_exec.risk, "can_open_position", return_value=(True, "ok")):
            try:
                clob_exec.open_paper_trade(
                    strategy="SCALPER",
                    market_polymarket_id="cid",
                    outcome_token_id="asset",
                    direction="NO",
                    size_usd=40.0,
                    run_id="run-x",
                    force_shadow=False,
                )
            finally:
                self._unpatch(patches)
        # _open_row called twice: once for real, once for shadow.
        assert m_open_row.call_count == 2
        kwargs_list = [c.kwargs for c in m_open_row.call_args_list]
        is_shadow_flags = [kw["is_shadow"] for kw in kwargs_list]
        assert sorted(is_shadow_flags) == [False, True]

    def test_global_cb_still_blocks_when_force_shadow_false(self):
        patches, (m_price, m_record, m_open_row, m_inc) = self._patch_common()
        with patch.object(clob_exec.risk, "can_open_position",
                          return_value=(False, "circuit_breaker_active")):
            try:
                clob_exec.open_paper_trade(
                    strategy="SCALPER",
                    market_polymarket_id="cid",
                    outcome_token_id="asset",
                    direction="NO",
                    size_usd=40.0,
                    run_id="run-x",
                    force_shadow=False,
                )
            finally:
                self._unpatch(patches)
        # Only the shadow row is opened; real was blocked by global CB.
        assert m_open_row.call_count == 1
        assert m_open_row.call_args.kwargs["is_shadow"] is True
