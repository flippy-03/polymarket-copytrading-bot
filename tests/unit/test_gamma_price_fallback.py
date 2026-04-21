"""Tests for the Gamma price fallback in clob_exec.

When the CLOB /price endpoint fails (typical near game resolution — the
orderbook dries up), the position manager was falling through without
evaluating the SL. Fix: get_token_price_resilient tries the CLOB first,
then Gamma's /markets outcomePrices mapped via clobTokenIds.
"""
from unittest.mock import patch, MagicMock

from src.strategies.common import clob_exec


YES_TOKEN = "111111111"
NO_TOKEN = "222222222"
CID = "0xabc"


def _gamma_response(yes_price: float, no_price: float) -> dict:
    return {
        "clobTokenIds": f'["{YES_TOKEN}", "{NO_TOKEN}"]',
        "outcomePrices": f'["{yes_price}", "{no_price}"]',
    }


class TestGammaFallback:

    def test_gamma_returns_yes_price(self):
        with patch("src.strategies.common.clob_exec.httpx.get") as m:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = [_gamma_response(0.74, 0.26)]
            m.return_value = resp
            price = clob_exec.get_token_price_via_gamma(CID, YES_TOKEN)
        assert price == 0.74

    def test_gamma_returns_no_price(self):
        with patch("src.strategies.common.clob_exec.httpx.get") as m:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = [_gamma_response(0.74, 0.26)]
            m.return_value = resp
            price = clob_exec.get_token_price_via_gamma(CID, NO_TOKEN)
        assert price == 0.26

    def test_gamma_unknown_token_returns_none(self):
        with patch("src.strategies.common.clob_exec.httpx.get") as m:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = [_gamma_response(0.74, 0.26)]
            m.return_value = resp
            price = clob_exec.get_token_price_via_gamma(CID, "9999")
        assert price is None

    def test_gamma_http_error_returns_none(self):
        with patch("src.strategies.common.clob_exec.httpx.get") as m:
            resp = MagicMock()
            resp.status_code = 500
            m.return_value = resp
            price = clob_exec.get_token_price_via_gamma(CID, YES_TOKEN)
        assert price is None

    def test_gamma_exception_returns_none(self):
        with patch("src.strategies.common.clob_exec.httpx.get",
                   side_effect=RuntimeError("net err")):
            price = clob_exec.get_token_price_via_gamma(CID, YES_TOKEN)
        assert price is None

    def test_gamma_invalid_price_returns_none(self):
        with patch("src.strategies.common.clob_exec.httpx.get") as m:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = [_gamma_response(1.5, -0.3)]
            m.return_value = resp
            assert clob_exec.get_token_price_via_gamma(CID, YES_TOKEN) is None
            assert clob_exec.get_token_price_via_gamma(CID, NO_TOKEN) is None


class TestResilientPrice:

    def test_clob_ok_skips_gamma(self):
        with patch.object(clob_exec, "get_token_price", return_value=0.55) as clob_m, \
             patch.object(clob_exec, "get_token_price_via_gamma") as gamma_m:
            price = clob_exec.get_token_price_resilient(YES_TOKEN, CID)
        assert price == 0.55
        clob_m.assert_called_once_with(YES_TOKEN)
        gamma_m.assert_not_called()

    def test_clob_none_falls_back_to_gamma(self):
        with patch.object(clob_exec, "get_token_price", return_value=None), \
             patch.object(clob_exec, "get_token_price_via_gamma", return_value=0.42) as g_m:
            price = clob_exec.get_token_price_resilient(YES_TOKEN, CID)
        assert price == 0.42
        g_m.assert_called_once_with(CID, YES_TOKEN)

    def test_clob_zero_falls_back_to_gamma(self):
        with patch.object(clob_exec, "get_token_price", return_value=0.0), \
             patch.object(clob_exec, "get_token_price_via_gamma", return_value=0.33) as g_m:
            price = clob_exec.get_token_price_resilient(YES_TOKEN, CID)
        assert price == 0.33
        g_m.assert_called_once()

    def test_both_fail_returns_none(self):
        with patch.object(clob_exec, "get_token_price", return_value=None), \
             patch.object(clob_exec, "get_token_price_via_gamma", return_value=None):
            price = clob_exec.get_token_price_resilient(YES_TOKEN, CID)
        assert price is None

    def test_no_condition_id_skips_fallback(self):
        with patch.object(clob_exec, "get_token_price", return_value=None), \
             patch.object(clob_exec, "get_token_price_via_gamma") as g_m:
            price = clob_exec.get_token_price_resilient(YES_TOKEN, None)
        assert price is None
        g_m.assert_not_called()
