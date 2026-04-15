"""
Basket Consensus daemon.

Modes:
  --build-only   Rebuild the 3 thematic baskets (Crypto/Economics/Politics) and exit.
  --run          Run monitor + executor loops in parallel (default when no flag).

Example:
  python scripts/run_basket_strategy.py --build-only
  python scripts/run_basket_strategy.py --run
"""
import argparse
import threading

from src.strategies.basket.basket_builder import BasketBuilder
from src.strategies.basket.basket_executor import BasketExecutor
from src.strategies.basket.basket_monitor import BasketMonitor
from src.utils.logger import logger


def cmd_build() -> None:
    builder = BasketBuilder()
    try:
        result = builder.build_all_baskets()
        logger.info(f"build_all_baskets result: {result}")
    finally:
        builder.close()


def cmd_run() -> None:
    monitor = BasketMonitor()
    executor = BasketExecutor()

    def _monitor():
        try:
            monitor.run_forever()
        finally:
            monitor.close()

    def _executor():
        try:
            executor.run_forever()
        finally:
            executor.close()

    threads = [
        threading.Thread(target=_monitor, name="basket-monitor", daemon=True),
        threading.Thread(target=_executor, name="basket-executor", daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def main() -> None:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group()
    group.add_argument("--build-only", action="store_true", help="build baskets and exit")
    group.add_argument("--run", action="store_true", help="run monitor + executor loops")
    args = p.parse_args()

    if args.build_only:
        cmd_build()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
