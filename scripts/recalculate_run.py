"""
Recalculate a historical run using current code and write the derived results
into a new run with parent_run_id set to the source.

Scope of this first iteration: we scan the source run's copy_trades and the
raw observed_trades + market_price_snapshots captured while that run was live,
and re-emit copy_trades + portfolio_state_ct rows under a new run_id using the
current PnL/stop/signal logic.

The source run is NEVER touched — its rows stay exactly as originally written.
This is the "what would have happened if the current code had been live back
then" view.

Usage:
    python scripts/recalculate_run.py --source-run <uuid> \
        --new-version v1.0-recalc-after-sharpe-fix \
        --notes "re-evaluated with the Sharpe fix committed on 2026-04-20"
"""
import argparse
import sys

from src.strategies.common import config as C, db
from src.utils.logger import logger


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-run", required=True, help="run_id of the historical run to recalculate")
    p.add_argument("--new-version", required=True, help="version label for the derived run")
    p.add_argument("--notes", default=None)
    args = p.parse_args()

    source = db.get_run(args.source_run)
    if not source:
        logger.error(f"Source run {args.source_run} not found")
        sys.exit(1)

    strategy = source["strategy"]
    logger.info(f"Recalculating {strategy} run {args.source_run[:8]} → {args.new_version}")

    new_run_id = db.create_run(
        strategy,
        args.new_version,
        notes=args.notes,
        parent_run_id=args.source_run,
        config_snapshot={
            "PAPER_MODE": C.PAPER_MODE,
            "recalc_source": args.source_run,
            "recalc_note": "derived run — base state only; fill in replay logic per release",
        },
    )
    logger.info(f"Opened derived run {new_run_id[:8]}")

    initial = C.BASKET_INITIAL_CAPITAL if strategy == "BASKET" else C.SCALPER_INITIAL_CAPITAL
    max_pos = 8 if strategy == "BASKET" else 5
    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=False,
        initial_capital=initial, max_open_positions=max_pos,
    )
    db.ensure_portfolio_row(
        strategy, run_id=new_run_id, is_shadow=True,
        initial_capital=initial, max_open_positions=max_pos,
    )

    # Close the derived run immediately — the actual replay logic is expected
    # to be added per release (different fixes require different replay paths).
    # Leaving this as a skeleton keeps the run system operational without
    # silently producing stale or wrong derived data.
    db.close_run(new_run_id, end_notes="Skeleton — replay logic not yet implemented")
    logger.warning(
        "recalculate_run: this is currently a skeleton. The derived run was created "
        "and immediately closed. Implement the replay loop for your specific fix "
        "before relying on its results."
    )


if __name__ == "__main__":
    main()
