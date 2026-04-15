"""
Scalper Rotator daemon.

Modes:
  --build-pool   Rebuild the scalper pool and exit.
  --run          Run copy_monitor loop (mirrors titulars in real-time).

Example:
  python scripts/run_scalper_strategy.py --build-pool
  python scripts/run_scalper_strategy.py --run
"""
import argparse

from src.strategies.scalper.copy_monitor import ScalperCopyMonitor
from src.strategies.scalper.pool_builder import ScalperPoolBuilder
from src.utils.logger import logger


def cmd_build_pool() -> None:
    b = ScalperPoolBuilder()
    try:
        result = b.build_pool()
        logger.info(f"build_pool result: {result}")
    finally:
        b.close()


def cmd_run() -> None:
    monitor = ScalperCopyMonitor()
    try:
        monitor.run_forever()
    finally:
        monitor.close()


def main() -> None:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group()
    group.add_argument("--build-pool", action="store_true", help="build scalper pool and exit")
    group.add_argument("--run", action="store_true", help="run copy_monitor loop")
    args = p.parse_args()

    if args.build_pool:
        cmd_build_pool()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
