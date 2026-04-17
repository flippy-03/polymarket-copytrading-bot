"""
Scalper V2 daemon.

Modes:
  --select-pool  Run composite scoring against wallet_profiles and persist 4 titulars.
  --run          Run copy_monitor loop (mirrors titulars in real-time). [default]

Example:
  python scripts/run_scalper_strategy.py --select-pool
  python scripts/run_scalper_strategy.py --run
"""
import argparse

from src.strategies.scalper.copy_monitor import ScalperCopyMonitor
from src.strategies.scalper.pool_selector import ScalperPoolSelector
from src.utils.logger import logger


def cmd_select_pool() -> None:
    selector = ScalperPoolSelector()
    candidates = selector.select()
    if not candidates:
        logger.warning("select_pool: no eligible candidates found in wallet_profiles")
        return
    selector.persist_selection(candidates)
    logger.info(f"select_pool: {len(candidates)} titulars persisted")
    for c in candidates:
        logger.info(f"  {c['wallet'][:10]}… types={c['approved_market_types']} score={c['composite_score']:.3f}")


def cmd_run() -> None:
    monitor = ScalperCopyMonitor()
    try:
        monitor.run_forever()
    finally:
        monitor.close()


def main() -> None:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group()
    group.add_argument("--select-pool", action="store_true", help="select titulars from wallet_profiles and exit")
    group.add_argument("--run", action="store_true", help="run copy_monitor loop (default)")
    args = p.parse_args()

    if args.select_pool:
        cmd_select_pool()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
