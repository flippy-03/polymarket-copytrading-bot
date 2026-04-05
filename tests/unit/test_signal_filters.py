"""
Unit tests for the price filter logic in src/signals/signal_engine.py

The filters are embedded in run_signal_engine(), so we replicate them here
as a pure function (same conditions, same order) and verify all boundary cases.

Filter order (from signal_engine.py lines ~370-410):
  1. price is None                             → SKIP
  2. YES and price > (1 - MIN_ENTRY_PRICE)     → SKIP (near resolution YES side)
  3. NO  and price < MIN_ENTRY_PRICE           → SKIP (near resolution NO side)
  4. entry = price (YES) or 1-price (NO)
  5. entry < MIN_ENTRY_PRICE                   → SKIP
  6. entry < MIN_CONTRARIAN_PRICE              → SKIP (market 80%+ resolved vs us)
  7. entry > (1 - MIN_CONTRARIAN_PRICE)        → SKIP (TP unreachable in binary market)
  → else: PASS, return entry
"""
import pytest

from src.utils.config import MIN_ENTRY_PRICE, MIN_CONTRARIAN_PRICE


def _apply_price_filters(price, direction: str) -> tuple[bool, str | float]:
    """
    Replicates signal_engine.py price filters.
    Returns (skip, reason_or_entry):
      skip=True  → (True, reason_string)
      skip=False → (False, entry_price)
    """
    if price is None:
        return True, "no_price"

    if direction == "YES" and price > (1 - MIN_ENTRY_PRICE):
        return True, "near_resolution_YES"

    if direction == "NO" and price < MIN_ENTRY_PRICE:
        return True, "near_resolution_NO"

    entry = price if direction == "YES" else round(1 - price, 4)

    if entry < MIN_ENTRY_PRICE:
        return True, "entry_below_min_entry"

    if entry < MIN_CONTRARIAN_PRICE:
        return True, "entry_below_contrarian_floor"

    if entry > (1 - MIN_CONTRARIAN_PRICE):
        return True, "entry_above_contrarian_ceiling"

    return False, entry


# ── None price ───────────────────────────────────────────────────────────────

class TestNonePrice:

    def test_yes_none_price_skipped(self):
        skip, reason = _apply_price_filters(None, "YES")
        assert skip is True
        assert reason == "no_price"

    def test_no_none_price_skipped(self):
        skip, reason = _apply_price_filters(None, "NO")
        assert skip is True
        assert reason == "no_price"


# ── Near-resolution filter ────────────────────────────────────────────────────

class TestNearResolutionFilter:

    def test_yes_skipped_when_yes_price_above_095(self):
        # MIN_ENTRY_PRICE=0.05 → ceiling = 1-0.05 = 0.95
        skip, reason = _apply_price_filters(0.96, "YES")
        assert skip is True
        assert reason == "near_resolution_YES"

    def test_yes_skipped_at_exactly_096(self):
        skip, _ = _apply_price_filters(0.96, "YES")
        assert skip is True

    def test_yes_passes_at_095(self):
        # 0.95 is NOT > 0.95, so it passes this filter (may still fail later)
        skip, _ = _apply_price_filters(0.95, "YES")
        # entry=0.95 > 0.80 (contrarian ceiling) → will be skipped by a later filter
        assert skip is True  # fails ceiling filter
        assert _ == "entry_above_contrarian_ceiling"

    def test_no_skipped_when_yes_price_below_005(self):
        skip, reason = _apply_price_filters(0.04, "NO")
        assert skip is True
        assert reason == "near_resolution_NO"

    def test_no_passes_at_005_yes_price(self):
        # price=0.05 is NOT < 0.05, passes this filter
        # entry = 1 - 0.05 = 0.95 → will fail contrarian ceiling
        skip, reason = _apply_price_filters(0.05, "NO")
        assert skip is True
        assert reason == "entry_above_contrarian_ceiling"


# ── MIN_ENTRY_PRICE floor ─────────────────────────────────────────────────────

class TestMinEntryPriceFloor:

    def test_yes_entry_below_min_skipped(self):
        # YES at yes_price=0.03 → entry=0.03 < MIN_ENTRY_PRICE (0.05)
        skip, reason = _apply_price_filters(0.03, "YES")
        assert skip is True
        assert reason == "entry_below_min_entry"

    def test_yes_entry_at_005_passes_floor(self):
        # entry=0.05 = MIN_ENTRY_PRICE → not < → passes floor (but fails contrarian floor)
        skip, reason = _apply_price_filters(0.05, "YES")
        assert skip is True
        assert reason == "entry_below_contrarian_floor"


# ── MIN_CONTRARIAN_PRICE floor ────────────────────────────────────────────────

class TestContrarianFloor:

    def test_yes_entry_015_skipped(self):
        # yes_price=0.15 → entry=0.15 < MIN_CONTRARIAN_PRICE (0.20)
        skip, reason = _apply_price_filters(0.15, "YES")
        assert skip is True
        assert reason == "entry_below_contrarian_floor"

    def test_no_entry_015_skipped(self):
        # yes_price=0.85 → entry=1-0.85=0.15 < 0.20
        skip, reason = _apply_price_filters(0.85, "NO")
        assert skip is True
        assert reason == "entry_below_contrarian_floor"

    def test_yes_entry_at_020_passes(self):
        # entry=0.20 = MIN_CONTRARIAN_PRICE → not < → passes
        skip, entry = _apply_price_filters(0.20, "YES")
        assert skip is False
        assert entry == 0.20

    def test_no_entry_at_020_passes(self):
        # yes_price=0.80 → entry=0.20 → passes
        skip, entry = _apply_price_filters(0.80, "NO")
        assert skip is False
        assert entry == 0.20


# ── 1 - MIN_CONTRARIAN_PRICE ceiling ─────────────────────────────────────────

class TestContrarianCeiling:

    def test_yes_entry_085_skipped(self):
        # yes_price=0.85 → entry=0.85 > 0.80 → TP unreachable
        skip, reason = _apply_price_filters(0.85, "YES")
        assert skip is True
        assert reason == "entry_above_contrarian_ceiling"

    def test_no_entry_085_skipped(self):
        # yes_price=0.15 → entry=1-0.15=0.85 > 0.80
        skip, reason = _apply_price_filters(0.15, "NO")
        assert skip is True
        assert reason == "entry_above_contrarian_ceiling"

    def test_yes_entry_at_080_passes(self):
        # entry=0.80 is NOT > 0.80 → passes ceiling
        skip, entry = _apply_price_filters(0.80, "YES")
        assert skip is False
        assert entry == 0.80

    def test_no_entry_at_080_passes(self):
        # yes_price=0.20 → entry=0.80 → passes
        skip, entry = _apply_price_filters(0.20, "NO")
        assert skip is False
        assert entry == 0.80


# ── Valid signals ─────────────────────────────────────────────────────────────

class TestValidSignals:

    def test_yes_midpoint_passes(self):
        skip, entry = _apply_price_filters(0.50, "YES")
        assert skip is False
        assert entry == 0.50

    def test_no_midpoint_passes(self):
        skip, entry = _apply_price_filters(0.50, "NO")
        assert skip is False
        assert entry == 0.50

    def test_yes_at_030_passes(self):
        skip, entry = _apply_price_filters(0.30, "YES")
        assert skip is False
        assert entry == 0.30

    def test_no_at_yes_price_070_passes(self):
        # yes_price=0.70 → entry=0.30 → valid
        skip, entry = _apply_price_filters(0.70, "NO")
        assert skip is False
        assert entry == 0.30

    def test_entry_range_is_symmetric(self):
        # Valid range for both YES and NO: entry in [0.20, 0.80]
        for p in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
            skip_yes, _ = _apply_price_filters(p, "YES")
            skip_no, _ = _apply_price_filters(1 - p, "NO")
            assert skip_yes is False, f"YES at {p} should pass"
            assert skip_no is False, f"NO at yes_price={1-p} (entry={p}) should pass"
