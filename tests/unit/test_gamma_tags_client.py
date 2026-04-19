"""Tests for gamma_tags_client — tag → market_type mapping.

The network + DB side is exercised via mocks; the pure mapping is tested
directly so changes to TAG_TO_TYPE don't silently regress.
"""
from unittest.mock import patch

from src.data import gamma_tags_client as gtc


class TestTagMapping:

    def test_weather_tag(self):
        assert gtc._niche_from_tags(["weather", "recurring"]) == "weather"

    def test_daily_temperature_is_weather(self):
        assert gtc._niche_from_tags(["daily-temperature", "highest-temperature"]) == "weather"

    def test_nfl_maps_to_sports_winner(self):
        assert gtc._niche_from_tags(["nfl", "super-bowl"]) == "sports_winner"

    def test_bitcoin_maps_to_crypto_above(self):
        assert gtc._niche_from_tags(["bitcoin", "crypto-prices"]) == "crypto_above"

    def test_unknown_tags_return_none(self):
        assert gtc._niche_from_tags(["some-random-city", "all"]) is None

    def test_empty_tags_return_none(self):
        assert gtc._niche_from_tags([]) is None

    def test_first_match_wins(self):
        # "all" appears first but is not mapped; "weather" second — weather wins
        assert gtc._niche_from_tags(["all", "weather", "nfl"]) == "weather"


class TestGetNicheForEvent:

    def setup_method(self):
        """Clear in-memory cache between tests."""
        gtc._mem_cache.clear()

    def test_empty_event_slug_returns_none(self):
        assert gtc.get_niche_for_event("") is None

    def test_cache_hit_memory(self):
        gtc._mem_cache["abc"] = (["weather"], "weather")
        # Should not hit DB or network
        with patch.object(gtc, "_cache_get_db") as mock_db, \
             patch.object(gtc, "_fetch_gamma_tags") as mock_fetch:
            result = gtc.get_niche_for_event("abc")
        assert result == "weather"
        mock_db.assert_not_called()
        mock_fetch.assert_not_called()

    def test_cache_hit_db_populates_memory(self):
        with patch.object(gtc, "_cache_get_db", return_value=(["nfl"], "sports_winner")), \
             patch.object(gtc, "_fetch_gamma_tags") as mock_fetch:
            result = gtc.get_niche_for_event("some-nfl-event")
        assert result == "sports_winner"
        mock_fetch.assert_not_called()
        assert gtc._mem_cache["some-nfl-event"] == (["nfl"], "sports_winner")

    def test_cache_miss_fetches_gamma_and_caches(self):
        with patch.object(gtc, "_cache_get_db", return_value=None), \
             patch.object(gtc, "_fetch_gamma_tags", return_value=["weather", "daily-temperature"]), \
             patch.object(gtc, "_cache_put_db") as mock_put:
            result = gtc.get_niche_for_event("wuhan-event")
        assert result == "weather"
        mock_put.assert_called_once()
        args, _ = mock_put.call_args
        assert args[0] == "wuhan-event"
        assert args[2] == "weather"

    def test_network_failure_returns_none_without_caching(self):
        with patch.object(gtc, "_cache_get_db", return_value=None), \
             patch.object(gtc, "_fetch_gamma_tags", return_value=None), \
             patch.object(gtc, "_cache_put_db") as mock_put:
            result = gtc.get_niche_for_event("unknown-event")
        assert result is None
        mock_put.assert_not_called()
        assert "unknown-event" not in gtc._mem_cache

    def test_no_matching_tag_caches_none(self):
        with patch.object(gtc, "_cache_get_db", return_value=None), \
             patch.object(gtc, "_fetch_gamma_tags", return_value=["all", "some-random"]), \
             patch.object(gtc, "_cache_put_db") as mock_put:
            result = gtc.get_niche_for_event("misc-event")
        assert result is None
        # Still cached — don't re-hit Gamma for known-None mapping
        mock_put.assert_called_once()
        assert mock_put.call_args[0][2] is None


class TestClassifyViaTags:

    def setup_method(self):
        gtc._mem_cache.clear()

    def test_uses_eventslug_from_market(self):
        market = {"eventSlug": "nfl-sunday-games", "question": "Will Patriots win?"}
        with patch.object(gtc, "get_niche_for_event", return_value="sports_winner") as m:
            result = gtc.classify_via_tags(market)
        assert result == "sports_winner"
        m.assert_called_once_with("nfl-sunday-games")

    def test_falls_back_to_events_array(self):
        market = {"events": [{"slug": "weather-tokyo"}], "question": "Temp in Tokyo?"}
        with patch.object(gtc, "get_niche_for_event", return_value="weather") as m:
            result = gtc.classify_via_tags(market)
        assert result == "weather"
        m.assert_called_once_with("weather-tokyo")

    def test_no_slug_returns_none(self):
        market = {"question": "Something?"}
        assert gtc.classify_via_tags(market) is None
