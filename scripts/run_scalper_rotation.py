"""
Scalper weekly rotation job.

Intended to be invoked by an external scheduler every Monday 00:00 UTC, or
manually with --force to force an immediate rotation.
"""
import argparse

from src.strategies.scalper.rotation_engine import RotationEngine
from src.utils.logger import logger


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="force rotation now (ignore schedule)")
    args = p.parse_args()

    engine = RotationEngine()
    try:
        reason = "MANUAL" if args.force else "SCHEDULED_WEEKLY"
        result = engine.execute_rotation(reason=reason)
        logger.info(f"Rotation complete: {result}")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
