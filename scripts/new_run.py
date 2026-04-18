"""
Create a fresh run for one or more strategies.

Procedure for each strategy:
  1. (Optional) Close all open real trades at current market price
  2. Close the current ACTIVE run
  3. Create a new ACTIVE run with a config snapshot
  4. Carry over specialist rankings (SPECIALIST) or pool entries (SCALPER)
  5. Seed portfolio rows at the specified capital

Usage:
    # Full reset — both strategies, $1000, close open positions
    python scripts/new_run.py --strategy ALL --version v2.0 --close-positions

    # Only SPECIALIST, inherit capital from old run
    python scripts/new_run.py --strategy SPECIALIST --version v2.1 \\
        --notes "tuned trailing stop"

    # Start completely clean (no pool/ranking carryover)
    python scripts/new_run.py --strategy SCALPER --version v3.0 \\
        --close-positions --no-carryover
"""
from __future__ import annotations

import argparse
import sys
import time

from src.strategies.common import clob_exec, config as C, db
from src.utils.logger import logger


def _close_open_positions(strategy: str, run_id: str) -> None:
    open_trades = db.list_open_trades(strategy=strategy, run_id=run_id, is_shadow=False)
    if not open_trades:
        logger.info(f"  [{strategy}] no open positions to close")
        return
    logger.info(f"  [{strategy}] closing {len(open_trades)} open position(s)…")
    closed = 0
    for trade in open_trades:
        try:
            clob_exec.close_paper_trade(trade["id"], "RUN_RESET")
            closed += 1
        except Exception as e:
            logger.warning(f"  [{strategy}] close {trade['id'][:8]}: {e}")
        time.sleep(0.05)
    logger.info(f"  [{strategy}] closed {closed}/{len(open_trades)} positions")


def _reset_strategy(
    strategy: str,
    version: str,
    capital: float,
    notes: str | None,
    close_positions: bool,
    carryover: bool,
) -> None:
    try:
        old_run_id = db.get_active_run(strategy, use_cache=False)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f"[{strategy}] active run: {old_run_id[:8]}…")

    if close_positions:
        _close_open_positions(strategy, old_run_id)

    logger.info(f"[{strategy}] closing run {old_run_id[:8]}…")
    db.close_run(old_run_id, end_notes=f"Closed on transition to {version}")

    config_snapshot = _build_config_snapshot(strategy)
    new_run_id = db.create_run(
        strategy,
        version,
        notes=notes,
        parent_run_id=None,
        config_snapshot=config_snapshot,
    )
    logger.info(f"[{strategy}] created run {new_run_id[:8]}… (version={version})")

    if strategy == "SPECIALIST" and carryover:
        n = db.carry_over_spec_ranking(old_run_id, new_run_id)
        logger.info(f"[{strategy}] migrated {n} spec_ranking row(s)")
    elif strategy == "SCALPER":
        # SCALPER V2 always re-bootstraps from wallet_profiles — carry-over is
        # broken by design (only preserved 5 legacy columns, lost V2 fields like
        # approved_market_types, composite_score, allocation_pct).
        from src.strategies.scalper.pool_selector import ScalperPoolSelector
        selector = ScalperPoolSelector(run_id=new_run_id)
        candidates = selector.select()
        selector.persist_selection(candidates)
        logger.info(f"[{strategy}] bootstrapped {len(candidates)} titulares via pool_selector")

    max_pos = 8  # sensible default for both strategies
    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=False,
        initial_capital=capital, max_open_positions=max_pos,
    )
    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=True,
        initial_capital=capital, max_open_positions=max_pos,
    )

    logger.info(
        f"[{strategy}] done — new run {new_run_id[:8]}… "
        f"capital=${capital:.0f} carryover={carryover}"
    )


def _build_config_snapshot(strategy: str) -> dict:
    if strategy == "SPECIALIST":
        return {
            "SPECIALIST_INITIAL_CAPITAL": C.SPECIALIST_INITIAL_CAPITAL,
            "SPECIALIST_TRADE_PCT": C.SPECIALIST_TRADE_PCT,
            "SPECIALIST_MAX_TRADE_USD": C.SPECIALIST_MAX_TRADE_USD,
            "SPECIALIST_MIN_TRADE_USD": C.SPECIALIST_MIN_TRADE_USD,
            "SPECIALIST_MAX_EXPOSURE_PCT": C.SPECIALIST_MAX_EXPOSURE_PCT,
            "SPECIALIST_CONTESTED_SIZE_MULT": C.SPECIALIST_CONTESTED_SIZE_MULT,
            "SIGNAL_CLEAN_RATIO": C.SIGNAL_CLEAN_RATIO,
            "SIGNAL_CONTESTED_RATIO": C.SIGNAL_CONTESTED_RATIO,
            "SPECIALIST_UNIVERSES": {
                k: {kk: vv for kk, vv in v.items() if kk != "market_types"}
                for k, v in C.SPECIALIST_UNIVERSES.items()
            },
            "TS_ACTIVATION": C.TS_ACTIVATION,
            "TS_TRAIL_PCT": C.TS_TRAIL_PCT,
            "PAPER_MODE": C.PAPER_MODE,
        }
    elif strategy == "SCALPER":
        return {
            "SCALPER_INITIAL_CAPITAL": C.SCALPER_INITIAL_CAPITAL,
            "SCALPER_ACTIVE_WALLETS": C.SCALPER_ACTIVE_WALLETS,
            "SCALPER_COPY_RATIO_MIN": C.SCALPER_COPY_RATIO_MIN,
            "SCALPER_COPY_RATIO_MAX": C.SCALPER_COPY_RATIO_MAX,
            "SCALPER_CONSECUTIVE_LOSS_LIMIT": C.SCALPER_CONSECUTIVE_LOSS_LIMIT,
            "MAX_DRAWDOWN_PCT": C.MAX_DRAWDOWN_PCT,
            "PAPER_MODE": C.PAPER_MODE,
        }
    return {"PAPER_MODE": C.PAPER_MODE}


def _default_capital(strategy: str) -> float:
    if strategy == "SPECIALIST":
        return C.SPECIALIST_INITIAL_CAPITAL
    if strategy == "SCALPER":
        return C.SCALPER_INITIAL_CAPITAL
    return C.BASKET_INITIAL_CAPITAL


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", required=True, choices=["SPECIALIST", "SCALPER", "ALL"])
    p.add_argument("--version", required=True, help="new run version label, e.g. v2.0")
    p.add_argument("--capital", type=float, default=None,
                   help="starting capital in USD (default: from config.py)")
    p.add_argument("--notes", default=None)
    p.add_argument("--close-positions", action="store_true",
                   help="close all open real trades before switching run")
    p.add_argument("--no-carryover", action="store_true",
                   help="do NOT carry over spec_ranking / scalper_pool to new run")
    args = p.parse_args()

    strategies = ["SPECIALIST", "SCALPER"] if args.strategy == "ALL" else [args.strategy]
    carryover = not args.no_carryover

    for strategy in strategies:
        cap = args.capital if args.capital is not None else _default_capital(strategy)
        _reset_strategy(
            strategy=strategy,
            version=args.version,
            capital=cap,
            notes=args.notes,
            close_positions=args.close_positions,
            carryover=carryover,
        )

    logger.info("All done.")


if __name__ == "__main__":
    main()
