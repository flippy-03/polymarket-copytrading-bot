"""Tests for niche_concentration penalty in pool_selector composite_score.

Validates:
  - concentration >= threshold → no penalty
  - concentration < threshold → linear decay toward PENALTY_MAX
  - concentration absent (None) → no penalty (backward compatible)
"""
from src.strategies.scalper.pool_selector import _composite_score
from src.strategies.common import config as C


def _args(**overrides):
    base = dict(
        type_hr=0.70,
        type_pf=2.0,
        type_tc=20,
        type_sharpe=1.0,
        worst_30d_hr=0.60,
        hr_variance=0.05,
        momentum=0.2,
        sharpe_proxy=1.0,
        confidence="HIGH",
        is_priority=False,
    )
    base.update(overrides)
    return base


class TestNicheConcentrationPenalty:

    def test_none_concentration_means_no_penalty(self):
        score_no = _composite_score(**_args(niche_concentration=None))
        score_baseline = _composite_score(**_args())
        assert score_no == score_baseline

    def test_at_threshold_no_penalty(self):
        score_full = _composite_score(**_args(niche_concentration=C.NICHE_CONCENTRATION_THRESHOLD))
        score_none = _composite_score(**_args(niche_concentration=None))
        assert abs(score_full - score_none) < 1e-4

    def test_above_threshold_no_penalty(self):
        score_high = _composite_score(**_args(niche_concentration=0.95))
        score_none = _composite_score(**_args(niche_concentration=None))
        assert abs(score_high - score_none) < 1e-4

    def test_below_threshold_linear_penalty(self):
        # concentration = 0 → penalty = PENALTY_MAX (full penalty)
        score_zero = _composite_score(**_args(niche_concentration=0.0))
        score_full = _composite_score(**_args(niche_concentration=C.NICHE_CONCENTRATION_THRESHOLD))
        expected_ratio = 1.0 - C.NICHE_CONCENTRATION_PENALTY_MAX
        assert abs(score_zero / score_full - expected_ratio) < 1e-3

    def test_half_threshold_half_penalty(self):
        # concentration = threshold/2 → penalty ~ PENALTY_MAX / 2
        half = C.NICHE_CONCENTRATION_THRESHOLD / 2
        score_half = _composite_score(**_args(niche_concentration=half))
        score_full = _composite_score(**_args(niche_concentration=C.NICHE_CONCENTRATION_THRESHOLD))
        expected = 1.0 - C.NICHE_CONCENTRATION_PENALTY_MAX * 0.5
        assert abs(score_half / score_full - expected) < 5e-3

    def test_penalty_does_not_flip_sign(self):
        # A barely-passing score should not go negative due to the penalty
        # (soft penalty should never turn a valid candidate into -1).
        score = _composite_score(**_args(
            niche_concentration=0.0,
            type_hr=0.55,  # right at min
            type_tc=8,     # right at min
        ))
        assert score >= 0.0
