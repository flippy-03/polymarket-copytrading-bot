"""
Close the ACTIVE run for a strategy and open a new one.

Trades that are still OPEN stay attached to the old (now CLOSED) run — their
lifecycle keeps running on their original run_id for immutability. Basket
membership and scalper pool are carried over to the new run so operations
continue without interruption. Portfolio state for the new run starts either
from the previous capital (default) or from the configured initial capital
(--reset-capital).

Usage:
    python scripts/close_run.py --strategy BASKET \
        --version v1.1-fix-consensus-window \
        --notes "widen consensus window 4h -> 6h after seeing too many misses"

    python scripts/close_run.py --strategy SCALPER \
        --version v2.0-new-sizing --reset-capital \
        --notes "switch to Kelly-based sizing; reset capital to test cleanly"
"""
import argparse
import sys

from src.strategies.common import config as C, db
from src.utils.logger import logger


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True, choices=["BASKET", "SCALPER"])
    p.add_argument("--version", required=True, help="new run version label")
    p.add_argument("--notes", default=None)
    p.add_argument(
        "--reset-capital",
        action="store_true",
        help="start the new run's portfolio from the configured initial capital "
             "instead of inheriting current_capital from the old run",
    )
    p.add_argument(
        "--no-carryover",
        action="store_true",
        help="do NOT copy basket_wallets/scalper_pool to the new run (start empty)",
    )
    args = p.parse_args()

    strategy = args.strategy

    try:
        old_run_id = db.get_active_run(strategy, use_cache=False)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f"[{strategy}] closing run {old_run_id[:8]}…")
    db.close_run(old_run_id, end_notes=f"Closed on transition to {args.version}")

    new_run_id = db.create_run(
        strategy,
        args.version,
        notes=args.notes,
        parent_run_id=None,
        config_snapshot={
            "PAPER_MODE": C.PAPER_MODE,
            "BASKET_CONSENSUS_THRESHOLD": C.BASKET_CONSENSUS_THRESHOLD,
            "BASKET_TIME_WINDOW_HOURS": C.BASKET_TIME_WINDOW_HOURS,
            "SCALPER_ACTIVE_WALLETS": C.SCALPER_ACTIVE_WALLETS,
            "SCALPER_COPY_RATIO_MIN": C.SCALPER_COPY_RATIO_MIN,
            "SCALPER_COPY_RATIO_MAX": C.SCALPER_COPY_RATIO_MAX,
            "MAX_DRAWDOWN_PCT": C.MAX_DRAWDOWN_PCT,
        },
    )
    logger.info(f"[{strategy}] opened run {new_run_id[:8]} (version={args.version})")

    # Carry over membership tables
    if not args.no_carryover:
        if strategy == "BASKET":
            copied = db.carry_over_basket_wallets(old_run_id, new_run_id)
            logger.info(f"[{strategy}] carried over {copied} basket_wallets rows")
        else:
            copied = db.carry_over_scalper_pool(old_run_id, new_run_id)
            logger.info(f"[{strategy}] carried over {copied} scalper_pool rows")

    # Seed portfolio rows for the new run (real + shadow)
    initial = C.BASKET_INITIAL_CAPITAL if strategy == "BASKET" else C.SCALPER_INITIAL_CAPITAL
    max_pos = 8 if strategy == "BASKET" else 5

    if args.reset_capital:
        real_capital = initial
        shadow_capital = initial
    else:
        old_real = db.get_portfolio(strategy, run_id=old_run_id, is_shadow=False)
        old_shadow = db.get_portfolio(strategy, run_id=old_run_id, is_shadow=True)
        real_capital = float((old_real or {}).get("current_capital") or initial)
        shadow_capital = float((old_shadow or {}).get("current_capital") or initial)

    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=False,
        initial_capital=real_capital, max_open_positions=max_pos,
    )
    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=True,
        initial_capital=shadow_capital, max_open_positions=max_pos,
    )

    logger.info(
        f"[{strategy}] done. real_capital=${real_capital:.2f} shadow_capital=${shadow_capital:.2f} "
        f"reset={args.reset_capital} carryover={not args.no_carryover}"
    )


if __name__ == "__main__":
    main()
