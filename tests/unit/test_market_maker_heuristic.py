"""Tests for _is_market_maker_heuristic in profile_enricher.

Uses synthetic trade distributions that mirror the real ZhangMuZhi.. wallet
(+$33k/day via REDEEM+MERGE on multi-outcome events) and a typical
directional trader for the negative control.
"""
from src.strategies.common.profile_enricher import _is_market_maker_heuristic


def _trade(
    side: str = "BUY",
    price: float = 0.50,
    event: str = "some-event",
    cid: str = "cond-1",
) -> dict:
    return {
        "side": side,
        "price": price,
        "eventSlug": event,
        "conditionId": cid,
    }


class TestMarketMakerDetection:

    def test_zhangmuzhi_profile_is_mm(self):
        """Mimic the real bot: 99% BUYs, many trades at 0.99, multi-outcome."""
        trades: list[dict] = []
        # 100 BUYs at 0.99 across 5 outcomes of event-A
        for i in range(100):
            cid = f"cond-A-{i % 5}"
            trades.append(_trade(side="BUY", price=0.99, event="event-A", cid=cid))
        # 100 BUYs at 0.999 across 4 outcomes of event-B
        for i in range(100):
            cid = f"cond-B-{i % 4}"
            trades.append(_trade(side="BUY", price=0.999, event="event-B", cid=cid))
        # 2 SELLs (trivial — needed to not divide by zero later)
        trades.append(_trade(side="SELL", price=0.50, event="event-C", cid="cond-C-1"))
        trades.append(_trade(side="SELL", price=0.50, event="event-D", cid="cond-D-1"))

        result = _is_market_maker_heuristic(trades)
        assert result["is_mm"] is True
        assert result["confidence"] == 1.0
        assert result["signals"]["buy_skew"] is True
        assert result["signals"]["edge_concentration"] is True
        assert result["signals"]["multi_outcome_presence"] is True

    def test_directional_trader_is_not_mm(self):
        """A normal trader: balanced BUY/SELL, spread prices, one outcome per event."""
        trades = []
        for i in range(50):
            trades.append(_trade(side="BUY", price=0.40 + i * 0.002, event=f"ev-{i}", cid=f"cid-{i}"))
        for i in range(50):
            trades.append(_trade(side="SELL", price=0.55 + i * 0.002, event=f"ev-{i}", cid=f"cid-{i}"))
        result = _is_market_maker_heuristic(trades)
        assert result["is_mm"] is False
        assert result["confidence"] < 0.5

    def test_buy_only_but_directional_not_mm(self):
        """Scalper who only buys but across different events (no multi-outcome)."""
        trades = []
        for i in range(60):
            # All BUYs but at moderate prices and each event has a single outcome
            trades.append(_trade(side="BUY", price=0.40 + (i % 10) * 0.02, event=f"ev-{i}", cid=f"cid-{i}"))
        # Add a few sells to fall below 98% threshold
        for i in range(3):
            trades.append(_trade(side="SELL", price=0.60, event=f"ev-{i}", cid=f"cid-{i}"))
        result = _is_market_maker_heuristic(trades)
        # 60 buys / 63 total = 95% < 98% threshold → not MM
        assert result["is_mm"] is False

    def test_insufficient_data_returns_false(self):
        trades = [_trade() for _ in range(10)]
        result = _is_market_maker_heuristic(trades)
        assert result["is_mm"] is False
        assert result["confidence"] == 0.0

    def test_one_signal_not_enough(self):
        """Only buy-skew triggered (no edge prices, no multi-outcome) → not MM."""
        trades = []
        for i in range(100):
            # All BUYs but mid-price, each its own event with single outcome
            trades.append(_trade(side="BUY", price=0.50, event=f"ev-{i}", cid=f"cid-{i}"))
        result = _is_market_maker_heuristic(trades)
        assert result["signals"]["buy_skew"] is True
        assert result["signals"]["edge_concentration"] is False
        assert result["signals"]["multi_outcome_presence"] is False
        assert result["is_mm"] is False

    def test_two_signals_enough(self):
        """Buy-skew + edge-concentration → MM even without multi-outcome."""
        trades = []
        for i in range(100):
            # All BUYs at 0.99 but each event has a single outcome
            trades.append(_trade(side="BUY", price=0.99, event=f"ev-{i}", cid=f"cid-{i}"))
        result = _is_market_maker_heuristic(trades)
        assert result["signals"]["buy_skew"] is True
        assert result["signals"]["edge_concentration"] is True
        assert result["is_mm"] is True
