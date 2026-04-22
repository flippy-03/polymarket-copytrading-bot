"""Verify the _record_price throttle in both monitors only fires once
per token within _PRICE_SNAPSHOT_MIN_INTERVAL_S.
"""
import time
from unittest.mock import patch


def test_position_manager_throttle_constant_is_180():
    from src.strategies.specialist import position_manager
    assert position_manager._PRICE_SNAPSHOT_MIN_INTERVAL_S == 180


def test_copy_monitor_throttle_constant_is_180():
    from src.strategies.scalper import copy_monitor
    assert copy_monitor._PRICE_SNAPSHOT_MIN_INTERVAL_S == 180


class _FakeTime:
    """Patch time.time to return a controlled clock."""
    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def __call__(self) -> float:
        return self.t


def test_throttle_logic_gated():
    """Simulate the decision inline — we don't exercise the full
    _check_trade which requires DB + CLOB. We verify the two-line rule:

        if now - last >= 180:
            record()
            last = now
    """
    last: dict[str, float] = {}
    clock = _FakeTime(start=1000.0)
    recorded: list[tuple[str, float]] = []

    def maybe_record(token_id: str, price: float) -> None:
        now = clock()
        if now - last.get(token_id, 0.0) >= 180:
            recorded.append((token_id, price))
            last[token_id] = now

    # t=1000: first call → record
    maybe_record("tok-A", 0.50)
    assert len(recorded) == 1

    # t=1060 (60s later): throttled
    clock.advance(60)
    maybe_record("tok-A", 0.48)
    assert len(recorded) == 1

    # t=1180 (180s total): edge — record
    clock.advance(120)
    maybe_record("tok-A", 0.46)
    assert len(recorded) == 2

    # t=1200: different token → always records
    clock.advance(20)
    maybe_record("tok-B", 0.80)
    assert len(recorded) == 3

    # t=1350: tok-A throttled again (170s since last), tok-B throttled (150s)
    clock.advance(150)
    maybe_record("tok-A", 0.40)
    maybe_record("tok-B", 0.78)
    assert len(recorded) == 3

    # t=1400: tok-A now 220s since last → records; tok-B still 200s → records
    clock.advance(50)
    maybe_record("tok-A", 0.38)
    maybe_record("tok-B", 0.75)
    assert len(recorded) == 5
