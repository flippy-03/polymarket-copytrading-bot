"""
Scalper V2 Pool Selector — selects 4 titulars from enriched wallet_profiles.

Replaces pool_builder.py. Zero API calls — purely database-driven.

Selection flow:
  1. Query wallet_profiles (HIGH/MEDIUM confidence, recently active, no cooldowns)
  2. Compute composite_score(wallet, market_type) for each pair
  3. Greedy selection with coverage optimisation: 4 titulars covering diverse types
  4. Each titular receives approved_market_types where they have proven edge
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from src.strategies.common import config as C, db
from src.strategies.specialist.market_type_classifier import classify  # noqa: F401
from src.utils.logger import logger


@dataclass
class TitularCandidate:
    wallet: str
    best_type: str
    best_score: float
    approved_types: list[str] = field(default_factory=list)
    type_scores: dict[str, float] = field(default_factory=dict)
    profile: dict = field(default_factory=dict)


class ScalperPoolSelector:
    """Select titulars from enriched wallet_profiles."""

    def __init__(self, *, run_id: str):
        self._run_id = run_id

    def select(
        self,
        num_titulars: int = C.SCALPER_ACTIVE_WALLETS,
        priority_types: list[str] | None = None,
    ) -> list[TitularCandidate]:
        """Select the best N titulars from enriched profiles.

        Args:
            num_titulars: How many titulars to select (default 4).
            priority_types: Market types to boost in scoring (from dashboard config).

        Returns:
            List of TitularCandidate, each with approved_market_types.
        """
        priority_types = priority_types or []

        # Load dashboard config overrides
        config = db.get_scalper_config(self._run_id)
        if not priority_types and config.get("priority_market_types"):
            priority_types = config["priority_market_types"]

        # Get active cooldowns to exclude
        cooldowns = db.list_active_cooldowns()
        cooldown_wallets: set[str] = set()
        cooldown_pairs: set[tuple[str, str]] = set()
        for cd in cooldowns:
            cooldown_pairs.add((cd["wallet_address"], cd["market_type"]))
            cooldown_wallets.add(cd["wallet_address"])

        # Fetch enriched candidates
        min_hr = config.get("min_hit_rate", C.SCALPER_MIN_HIT_RATE)
        min_tc = config.get("min_trade_count", C.SCALPER_MIN_TRADE_COUNT)
        profiles = db.list_eligible_scalper_candidates(limit=200)

        # Build (wallet, market_type, score) triplets
        triplets: list[tuple[str, str, float, dict]] = []
        for profile in profiles:
            wallet = profile["wallet"]
            type_hrs = profile.get("type_hit_rates") or {}
            type_pfs = profile.get("type_profit_factors") or {}
            type_tcs = profile.get("type_trade_counts") or {}
            type_sharpes = profile.get("type_sharpe_ratios") or {}

            for mtype, hr in type_hrs.items():
                tc = type_tcs.get(mtype, 0)
                if (wallet, mtype) in cooldown_pairs:
                    continue
                score = _composite_score(
                    type_hr=hr,
                    type_pf=type_pfs.get(mtype, 0),
                    type_tc=tc,
                    type_sharpe=type_sharpes.get(mtype, 0),
                    worst_30d_hr=profile.get("worst_30d_hit_rate") or 0,
                    hr_variance=profile.get("hit_rate_variance") or 0.15,
                    momentum=profile.get("momentum_score") or 0,
                    sharpe_proxy=profile.get("sharpe_proxy") or 0,
                    confidence=profile.get("profile_confidence") or "LOW",
                    is_priority=mtype in priority_types,
                    min_hr=min_hr,
                    min_tc=min_tc,
                )
                if score < 0:
                    continue
                triplets.append((wallet, mtype, score, profile))

        triplets.sort(key=lambda x: x[2], reverse=True)

        # Greedy selection: maximise score with type diversity
        selected: list[TitularCandidate] = []
        used_wallets: set[str] = set()
        covered_types: set[str] = set()

        for wallet, mtype, score, profile in triplets:
            if wallet in used_wallets:
                continue
            if len(selected) >= num_titulars:
                break
            # Prefer uncovered types; allow covered if score is exceptional
            if mtype in covered_types and score < 0.75:
                continue

            # Build this candidate's full approved_types list
            candidate = _build_candidate(
                wallet, profile, priority_types, min_hr, min_tc
            )

            selected.append(candidate)
            used_wallets.add(wallet)
            for t in candidate.approved_types:
                covered_types.add(t)

        logger.info(
            f"ScalperPoolSelector: selected {len(selected)} titulars "
            f"covering {len(covered_types)} market types"
        )
        for c in selected:
            logger.info(
                f"  {c.wallet[:10]}… score={c.best_score:.3f} "
                f"types={c.approved_types}"
            )
        return selected

    def persist_selection(
        self,
        candidates: list[TitularCandidate],
    ) -> None:
        """Write selected titulars to scalper_pool with V2 columns."""
        from src.strategies.scalper.titular_risk import compute_risk_config

        for cand in candidates:
            risk_cfg = compute_risk_config(cand.profile)
            db.update_scalper_status(
                cand.wallet, "ACTIVE_TITULAR", capital_usd=0, run_id=self._run_id,
            )
            db.update_scalper_pool_fields(
                cand.wallet,
                {
                    "approved_market_types": cand.approved_types,
                    "composite_score": cand.best_score,
                    "per_trader_loss_limit": risk_cfg["per_trader_loss_limit"],
                    "per_trader_consecutive_losses": 0,
                    "per_trader_is_broken": False,
                    "consecutive_wins": 0,
                    "allocation_pct": 1.0 / len(candidates),
                },
                run_id=self._run_id,
            )


def _composite_score(
    *,
    type_hr: float,
    type_pf: float,
    type_tc: int,
    type_sharpe: float,
    worst_30d_hr: float,
    hr_variance: float,
    momentum: float,
    sharpe_proxy: float,
    confidence: str,
    is_priority: bool,
    min_hr: float = C.SCALPER_MIN_HIT_RATE,
    min_tc: int = C.SCALPER_MIN_TRADE_COUNT,
) -> float:
    """Compute composite score for a (wallet, market_type) pair.

    Returns -1.0 if hard filters fail.
    """
    if type_tc < min_tc:
        return -1.0
    if type_hr < min_hr:
        return -1.0
    if worst_30d_hr < 0.40:
        return -1.0

    # Normalised components [0, 1]
    hr_score = min(1.0, max(0.0, (type_hr - 0.55) / 0.45))
    pf_score = min(1.0, type_pf / 5.0)
    sharpe_type_score = min(1.0, max(0.0, type_sharpe / 2.0))
    tc_score = min(1.0, math.log(type_tc + 1) / math.log(100))
    stab_score = max(0.0, 1.0 - hr_variance / 0.20)
    mom_score = min(1.0, max(0.0, (momentum + 0.5) / 1.0))
    conf_weight = 1.0 if confidence == "HIGH" else 0.7 if confidence == "MEDIUM" else 0.4
    priority_val = 1.0 if is_priority else 0.0

    raw = (
        0.30 * hr_score
        + 0.15 * pf_score
        + 0.15 * sharpe_type_score
        + 0.10 * tc_score
        + 0.10 * stab_score
        + 0.10 * mom_score
        + 0.05 * conf_weight
        + 0.05 * priority_val
    )

    # Consistency floor penalty
    if worst_30d_hr < 0.50:
        raw *= 0.7 + 0.3 * (worst_30d_hr / 0.50)

    return round(raw, 4)


def _build_candidate(
    wallet: str,
    profile: dict,
    priority_types: list[str],
    min_hr: float,
    min_tc: int,
) -> TitularCandidate:
    """Build a TitularCandidate with all approved types scored ≥ 0.50."""
    type_hrs = profile.get("type_hit_rates") or {}
    type_pfs = profile.get("type_profit_factors") or {}
    type_tcs = profile.get("type_trade_counts") or {}
    type_sharpes = profile.get("type_sharpe_ratios") or {}

    type_scores: dict[str, float] = {}
    for mtype, hr in type_hrs.items():
        score = _composite_score(
            type_hr=hr,
            type_pf=type_pfs.get(mtype, 0),
            type_tc=type_tcs.get(mtype, 0),
            type_sharpe=type_sharpes.get(mtype, 0),
            worst_30d_hr=profile.get("worst_30d_hit_rate") or 0,
            hr_variance=profile.get("hit_rate_variance") or 0.15,
            momentum=profile.get("momentum_score") or 0,
            sharpe_proxy=profile.get("sharpe_proxy") or 0,
            confidence=profile.get("profile_confidence") or "LOW",
            is_priority=mtype in priority_types,
            min_hr=min_hr,
            min_tc=min_tc,
        )
        if score >= 0.0:
            type_scores[mtype] = score

    approved = [t for t, s in type_scores.items() if s >= 0.50]
    approved.sort(key=lambda t: type_scores[t], reverse=True)

    best_type = approved[0] if approved else max(type_scores, key=type_scores.get, default="")
    best_score = type_scores.get(best_type, 0.0)

    return TitularCandidate(
        wallet=wallet,
        best_type=best_type,
        best_score=best_score,
        approved_types=approved,
        type_scores=type_scores,
        profile=profile,
    )
