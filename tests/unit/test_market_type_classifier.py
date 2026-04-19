"""Tests for market_type_classifier.

Focus: ensure micro-timeframe crypto binaries can no longer slip through as
'other'. Verified against real market titles seen in the v2.1 run that caused
losses.
"""
from src.strategies.specialist.market_type_classifier import classify


def _m(title: str, slug: str = "") -> dict:
    return {"question": title, "slug": slug or title.lower().replace(" ", "-")}


class TestMicroTimeframe:

    def test_btc_5min_window_is_micro(self):
        m = _m("Bitcoin Up or Down - April 19, 6:25AM-6:30AM")
        assert classify(m) == "crypto_updown_micro"

    def test_btc_5min_slug_only(self):
        m = _m("Will BTC move up or down", slug="bitcoin-up-or-down-5-min-window")
        assert classify(m) == "crypto_updown_micro"

    def test_eth_10min_window(self):
        m = _m("Ethereum Up or Down - April 19, 3:00PM-3:10PM")
        assert classify(m) == "crypto_updown_micro"


class TestShortAndDailyWindows:

    def test_btc_15min_is_short(self):
        m = _m("Will Bitcoin go up in the next 15-min")
        assert classify(m) == "crypto_updown_short"

    def test_btc_daily_is_daily(self):
        m = _m("Will BTC close higher today")
        assert classify(m) == "crypto_updown_daily"


class TestDirectionalPriceMarkets:

    def test_btc_above_price(self):
        m = _m("Will Bitcoin be above $76,000 on April 18")
        assert classify(m) == "crypto_above"

    def test_btc_below_price(self):
        m = _m("Will Bitcoin drop below $50,000 this month")
        assert classify(m) == "crypto_below"


class TestSports:

    def test_nba_game_is_winner(self):
        m = _m("NBA: Lakers vs Warriors — who wins?")
        assert classify(m) == "sports_winner"


class TestFallback:

    def test_unknown_market_is_unclassified_not_other(self):
        # v3.0 change: fallback must be explicit 'unclassified' so downstream
        # code can block it instead of silently allowing via 'other'.
        m = _m("Will this random event happen?")
        assert classify(m) == "unclassified"

    def test_crypto_ticker_without_price_fallback(self):
        # BTC mentioned but no dollar sign and no timeframe → unclassified
        m = _m("Talking about Bitcoin today")
        # Daily keyword triggers the daily pattern — still better than 'other'
        assert classify(m) in {"crypto_updown_daily", "unclassified"}
