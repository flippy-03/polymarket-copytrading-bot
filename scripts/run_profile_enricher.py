"""
Profile Enricher daemon.

Independent process that enriches wallets from both strategies (SPECIALIST via
`spec_ranking` + SCALPER via `scalper_pool`) into the `wallet_profiles` table.

The enricher is a best-effort background process:
  - It does NOT touch copy_trades, signals, or positions.
  - A failure here does NOT affect the live strategies.
  - Priority queue ensures the most relevant wallets (currently open, never
    enriched, stale) are processed first.

Usage:
  # Single pass over N wallets then exit (ideal for testing + cron)
  python -m scripts.run_profile_enricher --once --batch-size 1

  # Long-running daemon
  python -m scripts.run_profile_enricher --batch-size 3 --interval 90
"""
from __future__ import annotations

import argparse
import signal
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from src.strategies.common import db
from src.strategies.common.data_client import DataClient
from src.strategies.common.profile_enricher import (
    ProfileEnricher,
    STALE_AFTER_DAYS,
)
from src.utils.logger import logger

DEFAULT_BATCH = 3
DEFAULT_INTERVAL = 90
MIN_WALLET_INTERVAL = 30  # seconds between successive wallets

_shutdown = False


def _handle_sigterm(signum, frame):
    global _shutdown
    logger.info("Profile enricher received SIGTERM — shutting down…")
    _shutdown = True


# ───────────────────────────────────────────────────────────────────────────
# Source resolution + priority
# ───────────────────────────────────────────────────────────────────────────

def _gather_wallets(strategy_filter: str = "ALL") -> dict[str, dict]:
    """Merge wallet pools from both strategies, deduping by address."""
    merged: dict[str, dict] = {}

    if strategy_filter in ("ALL", "SPECIALIST"):
        try:
            for row in db.list_spec_ranking_addresses():
                w = row.get("wallet")
                if not w:
                    continue
                entry = merged.setdefault(w, {
                    "wallet": w,
                    "strategies": [],
                    "specialist_score": None,
                    "scalper_rank": None,
                    "scalper_status": None,
                })
                if "SPECIALIST" not in entry["strategies"]:
                    entry["strategies"].append("SPECIALIST")
                # Keep the highest specialist_score across (wallet, universe)
                score = row.get("specialist_score")
                if score is not None and (entry["specialist_score"] is None or
                                          score > entry["specialist_score"]):
                    entry["specialist_score"] = score
        except Exception as e:
            logger.warning(f"  enricher: list_spec_ranking failed: {e}")

    if strategy_filter in ("ALL", "SCALPER"):
        try:
            run_id = db.get_active_run("SCALPER")
        except Exception as e:
            logger.debug(f"  enricher: no active SCALPER run: {e}")
            run_id = None
        if run_id:
            try:
                for row in db.list_scalper_pool_addresses(run_id=run_id):
                    w = row.get("wallet_address")
                    if not w:
                        continue
                    entry = merged.setdefault(w, {
                        "wallet": w,
                        "strategies": [],
                        "specialist_score": None,
                        "scalper_rank": None,
                        "scalper_status": None,
                    })
                    if "SCALPER" not in entry["strategies"]:
                        entry["strategies"].append("SCALPER")
                    entry["scalper_rank"] = row.get("rank_position")
                    entry["scalper_status"] = row.get("status")
            except Exception as e:
                logger.warning(f"  enricher: list_scalper_pool failed: {e}")

    return merged


def _get_open_position_wallets() -> set[str]:
    """Wallets currently source of an OPEN copy_trade (mostly SCALPER mirrors,
    since SPECIALIST trade metadata doesn't yet carry the specialist list —
    that's P-E3). Best-effort: returns empty on any failure."""
    wallets: set[str] = set()
    for strategy in ("SCALPER", "SPECIALIST"):
        try:
            run_id = db.get_active_run(strategy)
        except Exception:
            continue
        try:
            rows = db.list_open_trades(
                strategy=strategy, run_id=run_id, is_shadow=False
            )
        except Exception:
            continue
        for t in rows or []:
            src = t.get("source_wallet")
            if src:
                wallets.add(src)
    return wallets


def _priority_for(wallet_ctx: dict, *, open_wallets: set[str]) -> float:
    """Higher score = process first."""
    base = wallet_ctx.get("specialist_score") or 0.0
    rank = wallet_ctx.get("scalper_rank")
    if rank and rank > 0:
        base = max(base, 1.0 / rank)

    if wallet_ctx["wallet"] in open_wallets:
        base += 3.0

    existing = db.get_wallet_profile(wallet_ctx["wallet"])
    if existing is None:
        base += 1.5
    else:
        enriched_at = existing.get("enriched_at") or 0
        age_days = (time.time() - enriched_at) / 86400 if enriched_at else 999
        if age_days >= STALE_AFTER_DAYS:
            base += 0.5
        else:
            base -= 1.0  # recently enriched: low priority
        wallet_ctx["_prev_specialist_at"] = existing.get("detected_by_specialist_at")
        wallet_ctx["_prev_scalper_at"] = existing.get("detected_by_scalper_at")

    return base


# ───────────────────────────────────────────────────────────────────────────
# Main tick
# ───────────────────────────────────────────────────────────────────────────

def _run_one_tick(
    enricher: ProfileEnricher,
    *,
    batch_size: int,
    strategy_filter: str,
) -> int:
    """Process one batch. Returns the number of wallets successfully enriched."""
    wallets = _gather_wallets(strategy_filter)
    if not wallets:
        logger.info("  enricher: no wallets from either strategy pool")
        return 0

    open_wallets = _get_open_position_wallets()

    ranked = sorted(
        wallets.values(),
        key=lambda ctx: _priority_for(ctx, open_wallets=open_wallets),
        reverse=True,
    )
    top = ranked[:batch_size]
    processed = 0

    logger.info(
        f"  enricher: {len(wallets)} wallets in pool, processing top {len(top)}"
    )

    for idx, ctx in enumerate(top):
        if _shutdown:
            break
        wallet = ctx["wallet"]
        try:
            row = enricher.enrich_wallet(
                wallet,
                strategies_active=ctx.get("strategies") or [],
                specialist_score=ctx.get("specialist_score"),
                scalper_rank=ctx.get("scalper_rank"),
                scalper_status=ctx.get("scalper_status"),
                previous_detected_specialist_at=ctx.get("_prev_specialist_at"),
                previous_detected_scalper_at=ctx.get("_prev_scalper_at"),
            )
            if not row:
                logger.info(f"  enricher: skipped {wallet[:10]}… (no data)")
                continue
            db.upsert_wallet_profile(row)
            processed += 1
            logger.info(
                f"  enriched {wallet[:10]}… "
                f"archetype={row.get('primary_archetype')} "
                f"rarity={row.get('rarity_tier')} "
                f"conf={row.get('profile_confidence')} "
                f"trades={row.get('trades_analyzed')} "
                f"domains={row.get('domain_expertise_breadth')}"
            )
        except Exception as e:
            logger.warning(f"  enricher: {wallet[:10]}… failed: {e}")

        # Rate limit between wallets (skip sleep after the last one)
        if idx < len(top) - 1 and not _shutdown:
            time.sleep(MIN_WALLET_INTERVAL)

    return processed


# ───────────────────────────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Profile enricher daemon")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help=f"wallets per tick (default: {DEFAULT_BATCH})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"seconds between ticks (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--strategy", choices=["ALL", "SPECIALIST", "SCALPER"],
                        default="ALL", help="filter wallet source")
    parser.add_argument("--once", action="store_true",
                        help="run one batch and exit (testing / cron mode)")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    data = DataClient()
    enricher = ProfileEnricher(data)
    logger.info(
        f"=== profile_enricher starting · batch={args.batch_size} "
        f"interval={args.interval}s strategy={args.strategy} "
        f"{'(once)' if args.once else ''} ==="
    )

    try:
        tick = 0
        while not _shutdown:
            tick += 1
            start = time.time()
            logger.info(f"=== enricher tick #{tick} ===")
            try:
                n = _run_one_tick(
                    enricher,
                    batch_size=args.batch_size,
                    strategy_filter=args.strategy,
                )
                logger.info(f"  tick #{tick}: {n} wallets enriched")
            except Exception as e:
                logger.error(f"  tick failed: {e}", exc_info=True)

            if args.once:
                break

            elapsed = time.time() - start
            sleep_s = max(5, args.interval - elapsed)
            if not _shutdown:
                time.sleep(sleep_s)
    finally:
        data.close()
        logger.info("=== profile_enricher stopped ===")


if __name__ == "__main__":
    main()
