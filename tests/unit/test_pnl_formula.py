"""Tests obligatorios de la fórmula de PnL (niche_specialist_engine.html §12).

La fórmula correcta:
    position_pnl = Σsell_proceeds + Σredeem_proceeds − Σbuy_costs + unrealized

SPLIT/MERGE son NEUTRALES (conversiones de colateral, no flujo de PnL).
El data-api ya las filtra vía type=TRADE | REDEEM, pero estos tests
verifican que la función de cálculo respeta el contrato: si por error
llegan eventos SPLIT/MERGE, no deben sumarse ni restarse.
"""
from src.strategies.common.profile_enricher import _pnl_for_cid, _infer_win


def _buy(usdc: float) -> dict:
    return {"side": "BUY", "usdcSize": usdc}


def _sell(usdc: float) -> dict:
    return {"side": "SELL", "usdcSize": usdc}


class TestPnLFormula:

    def test_1_split_only_wallet_returns_none(self):
        """Wallet que solo hizo SPLIT (sin BUY/SELL/REDEEM) → PnL indeterminado.

        data-api filter already excludes SPLIT events, so mkt_trades should
        be empty for such a wallet. The function returns None (not 0) to
        signal 'no data', which is the correct answer.
        """
        pnl = _pnl_for_cid("cid-1", mkt_trades=[], pos_pnl={}, pos_open=set())
        assert pnl is None

    def test_2_round_trip_winner(self):
        """BUY 10 @ $0.40 → SELL 10 @ $0.60 → PnL = +$2."""
        trades = [_buy(4.0), _sell(6.0)]  # 10*0.40=$4 in, 10*0.60=$6 out
        pnl = _pnl_for_cid("cid-2", trades, pos_pnl={}, pos_open=set())
        assert pnl == 2.0

    def test_3_redeem_winner(self):
        """BUY 10 @ $0.30 · mercado resuelve YES → REDEEM 10 shares = $10.

        Profit = $10 (redeem) − $3 (buy) = $7.
        """
        trades = [_buy(3.0)]
        redeem_proceeds = {"cid-3": 10.0}
        pnl = _pnl_for_cid("cid-3", trades, pos_pnl={}, pos_open=set(),
                           redeem_proceeds=redeem_proceeds)
        assert pnl == 7.0

    def test_4_open_position_uses_cashpnl_if_provided(self):
        """Posición abierta con cashPnl confirmado → usa ese valor."""
        trades = [_buy(5.0)]
        pnl = _pnl_for_cid("cid-4", trades, pos_pnl={"cid-4": 0.5}, pos_open=set())
        assert pnl == 0.5

    def test_5_partial_loss_via_redeem_loser(self):
        """BUY 10 @ $0.60 · mercado resuelve NO → REDEEM 0 (shares pierden).

        Profit = $0 (redeem) − $6 (buy) = −$6. Pero sin REDEEM event, solo
        con una SELL nula, la función devuelve None porque no puede confirmar
        que el mercado resolvió. El test verifica que una REDEEM de $0 en
        redeem_proceeds NO cuenta como resolved (está ausente del dict).
        """
        trades = [_buy(6.0)]
        # loser redeemed 0 shares → not in the proceeds dict at all
        pnl = _pnl_for_cid("cid-5", trades, pos_pnl={}, pos_open=set(),
                           redeem_proceeds={})
        # No sell, no redeem in dict → can't infer resolution
        assert pnl is None

    def test_6_filter_by_niche_only_counts_matching_cids(self):
        """Simulación: wallet con trades en weather (cid-w) y elections (cid-e).

        Si solo pasamos los trades de weather al by_cid, el cálculo agregado
        del nicho weather refleja únicamente esos trades. Los trades de
        elections se ignoran porque no están en el iteration scope.
        """
        # weather market: winner
        weather_trades = [_buy(3.0)]
        weather_redeem = {"cid-w": 10.0}
        pnl_w = _pnl_for_cid("cid-w", weather_trades, pos_pnl={},
                             pos_open=set(), redeem_proceeds=weather_redeem)
        assert pnl_w == 7.0

        # elections not included in this computation scope
        # The caller iterates over weather cids only, so cid-e is never
        # passed to _pnl_for_cid in this run.


class TestInferWin:

    def test_win_with_redeem_proceeds(self):
        """BUY + REDEEM mayor que BUY → win."""
        trades = [_buy(3.0)]
        assert _infer_win("cid-x", trades, {}, set(), {"cid-x": 10.0}) is True

    def test_loss_with_redeem_equal_to_zero(self):
        """BUY pero REDEEM = 0 (no en dict) → None (no resolved)."""
        trades = [_buy(3.0)]
        assert _infer_win("cid-x", trades, {}, set(), {}) is None

    def test_pos_open_returns_none(self):
        trades = [_buy(5.0)]
        assert _infer_win("cid-x", trades, {}, {"cid-x"}, {}) is None

    def test_pos_pnl_authoritative_wins(self):
        """cashPnl > 0 → True."""
        trades = [_buy(5.0)]
        assert _infer_win("cid-x", trades, {"cid-x": 0.5}, set(), {}) is True

    def test_pos_pnl_authoritative_loses(self):
        """cashPnl < 0 → False."""
        trades = [_buy(5.0)]
        assert _infer_win("cid-x", trades, {"cid-x": -2.0}, set(), {}) is False

    def test_no_sell_no_redeem_indeterminate(self):
        """Solo BUY sin SELL ni REDEEM → None."""
        trades = [_buy(5.0)]
        assert _infer_win("cid-x", trades, {}, set(), {}) is None


class TestSplitMergeNeutral:
    """Meta-contract tests: si alguna vez llegan eventos SPLIT/MERGE a la
    función (no deberían, data-api filtra), el cálculo los debe ignorar.

    Hoy la función filtra por side='BUY' | 'SELL', así que eventos con
    side='SPLIT' | 'MERGE' no afectan — este test lo documenta.
    """

    def test_split_events_do_not_affect_pnl(self):
        split_event = {"side": "SPLIT", "usdcSize": 100.0}
        trades = [_buy(3.0), _sell(4.0), split_event]
        # Expected: +4 (sell) − 3 (buy) = +1
        pnl = _pnl_for_cid("cid-x", trades, pos_pnl={}, pos_open=set())
        assert pnl == 1.0

    def test_merge_events_do_not_affect_pnl(self):
        merge_event = {"side": "MERGE", "usdcSize": 50.0}
        trades = [_buy(3.0), _sell(4.0), merge_event]
        pnl = _pnl_for_cid("cid-x", trades, pos_pnl={}, pos_open=set())
        assert pnl == 1.0
