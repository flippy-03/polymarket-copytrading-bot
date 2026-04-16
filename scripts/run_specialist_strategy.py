"""
Specialist Edge daemon script.

Usage:
  python -m scripts.run_specialist_strategy --bootstrap   # Seed the DB (1 scan per universe)
  python -m scripts.run_specialist_strategy --run         # Start the main daemon loop

The daemon calls SlotOrchestrator.tick() every 60 seconds.
A FULL type-rankings recomputation runs every TYPE_RECOMPUTE_INTERVAL_HOURS.
"""
import argparse
import signal
import sys
import time

# Load env first
from dotenv import load_dotenv
load_dotenv()

from src.strategies.common import config as C, db
from src.strategies.common.clob_exec import evaluate_shadow_stops
from src.strategies.common.data_client import DataClient
from src.strategies.common.gamma_client import GammaClient
from src.strategies.specialist.ranking_db import upsert_profile
from src.strategies.specialist.slot_orchestrator import SlotOrchestrator
from src.strategies.specialist.specialist_profiler import SpecialistProfiler
from src.strategies.specialist.type_rankings import recompute_all_type_rankings
from src.strategies.specialist.universe_config import UNIVERSES, market_types_for
from src.utils.logger import logger

STRATEGY = "SPECIALIST"
DAEMON_INTERVAL = 60          # seconds per tick
TYPE_RECOMPUTE_EVERY = int(C.TYPE_RECOMPUTE_INTERVAL_HOURS * 3600)

_shutdown = False


def _handle_sigterm(signum, frame):
    global _shutdown
    logger.info("Received SIGTERM — shutting down gracefully…")
    _shutdown = True


def _bootstrap(run_id: str) -> None:
    """
    Seed the specialist ranking DB with an initial scan.
    For each universe: scan 1 market, evaluate all holders, persist profiles.
    """
    logger.info("=== BOOTSTRAP: seeding specialist rankings ===")
    gamma = GammaClient()
    data = DataClient()
    profiler = SpecialistProfiler(data)

    try:
        for universe, cfg in UNIVERSES.items():
            target_types = market_types_for(universe)
            logger.info(f"Bootstrap [{universe}] types={target_types}")

            from src.strategies.specialist.market_scanner import find_candidate_markets
            markets = find_candidate_markets(
                market_types=target_types,
                gamma=gamma,
                limit_per_type=2,
            )
            if not markets:
                logger.warning(f"  bootstrap: no markets found for {universe}")
                continue

            # Scan holders of first 2 markets
            from src.strategies.common.data_client import DataClient as _DC
            scanned = 0
            for mkt in markets[:2]:
                cid = mkt.get("conditionId")
                if not cid:
                    continue
                try:
                    holders = data.get_market_holders(cid, limit=50)
                except Exception as e:
                    logger.warning(f"  bootstrap: get_holders {cid[:12]}…: {e}")
                    continue

                for holder in holders:
                    addr = holder.get("proxyWallet") or holder.get("address")
                    if not addr:
                        continue
                    try:
                        sp = profiler.profile(addr, universe, target_types)
                        if sp:
                            upsert_profile(sp, run_id)
                            scanned += 1
                            logger.info(
                                f"  bootstrap: found {addr[:10]}… "
                                f"hr={sp.universe_hit_rate:.0%} "
                                f"trades={sp.universe_trades} "
                                f"score={sp.specialist_score:.3f}"
                            )
                    except Exception as e:
                        logger.debug(f"  bootstrap: profile {addr[:10]}…: {e}")
                    time.sleep(0.2)

            logger.info(f"  bootstrap [{universe}]: {scanned} specialists found")

        # Initial type rankings computation
        recompute_all_type_rankings()
        logger.info("=== BOOTSTRAP complete ===")
    finally:
        gamma.close()
        data.close()


def _run(run_id: str) -> None:
    """Main daemon loop."""
    signal.signal(signal.SIGTERM, _handle_sigterm)

    logger.info("=== SPECIALIST EDGE daemon starting ===")

    # Ensure portfolio rows exist
    db.ensure_portfolio_row(
        STRATEGY,
        run_id=run_id,
        is_shadow=False,
        initial_capital=C.SPECIALIST_INITIAL_CAPITAL,
        max_open_positions=sum(cfg["max_slots"] for cfg in UNIVERSES.values()),
    )
    db.ensure_portfolio_row(
        STRATEGY,
        run_id=run_id,
        is_shadow=True,
        initial_capital=C.SPECIALIST_INITIAL_CAPITAL,
        max_open_positions=sum(cfg["max_slots"] for cfg in UNIVERSES.values()),
    )
    logger.info(f"Portfolio rows ensured for run={run_id[:8]}…")

    gamma = GammaClient()
    data = DataClient()
    orchestrator = SlotOrchestrator(gamma, data, run_id)

    last_type_recompute = 0
    tick_count = 0

    try:
        while not _shutdown:
            tick_start = time.time()
            tick_count += 1
            logger.info(f"=== tick #{tick_count} ===")

            # Periodic type ranking recomputation
            if tick_start - last_type_recompute > TYPE_RECOMPUTE_EVERY:
                try:
                    scores = recompute_all_type_rankings()
                    logger.info(f"Type rankings recomputed: {len(scores)} types")
                except Exception as e:
                    logger.warning(f"Type rankings recompute failed: {e}")
                last_type_recompute = tick_start

            # Evaluate shadow stops before main tick
            try:
                frozen = evaluate_shadow_stops(STRATEGY, run_id=run_id)
                if frozen:
                    logger.info(f"Shadow stops frozen this tick: {frozen}")
            except Exception as e:
                logger.warning(f"evaluate_shadow_stops failed: {e}")

            # Main tick
            try:
                summary = orchestrator.tick()
                logger.info(
                    f"Tick summary: closures={summary['closures']} "
                    f"opened={summary['opened']} "
                    f"skipped={summary['skipped']}"
                )
            except Exception as e:
                logger.error(f"Tick failed: {e}", exc_info=True)

            elapsed = time.time() - tick_start
            sleep_time = max(0, DAEMON_INTERVAL - elapsed)
            logger.debug(f"Tick took {elapsed:.1f}s, sleeping {sleep_time:.1f}s")

            if not _shutdown:
                time.sleep(sleep_time)
    finally:
        logger.info("Shutting down SPECIALIST daemon…")
        gamma.close()
        data.close()


def main():
    parser = argparse.ArgumentParser(description="Specialist Edge strategy daemon")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bootstrap", action="store_true",
                       help="Seed the specialist ranking DB then exit")
    group.add_argument("--run", action="store_true",
                       help="Start the main daemon loop")
    args = parser.parse_args()

    run_id = db.get_active_run(STRATEGY)
    logger.info(f"Using run_id={run_id[:8]}… for strategy={STRATEGY}")

    if args.bootstrap:
        _bootstrap(run_id)
    elif args.run:
        _run(run_id)


if __name__ == "__main__":
    main()
