#!/usr/bin/env python3
"""
Daily roadmap snapshot generator.

Reads current configuration (config.py), database state (portfolios, titulars,
enriched profiles) and generates a structured JSON snapshot for the /roadmap
dashboard page. Runs daily via systemd timer.

Usage:
    python scripts/update_roadmap_snapshot.py [--once]
"""
from __future__ import annotations

import argparse
import time

from src.strategies.common import config as C, db
from src.utils.logger import logger


def _build_snapshot() -> dict:
    """Build the roadmap snapshot dict."""
    now_ts = int(time.time())

    # ── Strategy config values ─────────────────────────────
    specialist_config = {
        "initial_capital": C.SPECIALIST_INITIAL_CAPITAL,
        "universes": {
            name: {
                "capital_pct": u["capital_pct"],
                "max_slots": u["max_slots"],
                "market_types": u["market_types"],
            }
            for name, u in C.SPECIALIST_UNIVERSES.items()
        },
        "trailing_stop": {
            "activation": C.TS_ACTIVATION,
            "trail_pct": C.TS_TRAIL_PCT,
        },
        "consecutive_loss_limit": C.SPECIALIST_CONSECUTIVE_LOSS_LIMIT,
        "signal_clean_ratio": C.SIGNAL_CLEAN_RATIO,
        "signal_min_specialists": C.SIGNAL_MIN_SPECIALISTS,
        "market_filters": {
            "min_volume_24h": C.SPECIALIST_MARKET_MIN_VOLUME_24H,
            "max_hours": C.SPECIALIST_MARKET_MAX_HOURS,
            "price_range": [C.SPECIALIST_MARKET_MIN_PRICE, C.SPECIALIST_MARKET_MAX_PRICE],
            "max_spread": C.SPECIALIST_MARKET_MAX_SPREAD,
        },
        "trade_sizing": {
            "trade_pct": C.SPECIALIST_TRADE_PCT,
            "max_trade_usd": C.SPECIALIST_MAX_TRADE_USD,
            "min_trade_usd": C.SPECIALIST_MIN_TRADE_USD,
        },
    }

    scalper_config = {
        "initial_capital": C.SCALPER_INITIAL_CAPITAL,
        "active_wallets": C.SCALPER_ACTIVE_WALLETS,
        "min_hit_rate": C.SCALPER_MIN_HIT_RATE,
        "min_trade_count": C.SCALPER_MIN_TRADE_COUNT,
        "trade_pct": C.SCALPER_TRADE_PCT,
        "max_trade_pct": C.SCALPER_MAX_TRADE_PCT,
        "min_per_trade": C.SCALPER_MIN_PER_TRADE,
        "bonus_pct": C.SCALPER_BONUS_PCT,
        "max_open_positions": C.SCALPER_MAX_OPEN_POSITIONS,
        "health_check_hours": C.SCALPER_HEALTH_CHECK_HOURS,
        "cooldown_days_base": C.SCALPER_COOLDOWN_DAYS_BASE,
        "consecutive_loss_limit": C.SCALPER_CONSECUTIVE_LOSS_LIMIT,
        "priority_boost": C.SCALPER_PRIORITY_BOOST,
        "monitor_interval_seconds": C.SCALPER_MONITOR_INTERVAL_SECONDS,
        "trailing_stop": {
            "activation": C.TS_ACTIVATION,
            "trail_pct": C.TS_TRAIL_PCT,
        },
    }

    risk_config = {
        "max_drawdown_pct": C.MAX_DRAWDOWN_PCT,
        "daily_loss_limit": C.DAILY_LOSS_LIMIT,
        "max_per_market_pct": C.MAX_PER_MARKET_PCT,
        "max_per_trade_pct": C.MAX_PER_TRADE_PCT,
        "timeout_days": C.TIMEOUT_DAYS,
        "min_liquidity_24h": C.MIN_LIQUIDITY_24H,
        "max_slippage": C.MAX_SLIPPAGE,
        "max_entry_drift": C.MAX_ENTRY_DRIFT,
    }

    # ── Database state ──────────────────────────────────────
    db_state = {}
    try:
        # Specialist portfolio
        spec_run = db.get_active_run("SPECIALIST")
        spec_portfolio = db.get_portfolio("SPECIALIST", run_id=spec_run) if spec_run else None
        db_state["specialist_portfolio"] = {
            "current_capital": float((spec_portfolio or {}).get("current_capital") or 0),
            "total_pnl": float((spec_portfolio or {}).get("total_pnl") or 0),
            "total_trades": int((spec_portfolio or {}).get("total_trades") or 0),
            "win_rate": float((spec_portfolio or {}).get("win_rate") or 0),
            "is_circuit_broken": bool((spec_portfolio or {}).get("is_circuit_broken")),
        } if spec_portfolio else None
    except Exception:
        db_state["specialist_portfolio"] = None

    try:
        # Scalper portfolio
        scalper_run = db.get_active_run("SCALPER")
        scalper_portfolio = db.get_portfolio("SCALPER", run_id=scalper_run) if scalper_run else None
        db_state["scalper_portfolio"] = {
            "current_capital": float((scalper_portfolio or {}).get("current_capital") or 0),
            "total_pnl": float((scalper_portfolio or {}).get("total_pnl") or 0),
            "total_trades": int((scalper_portfolio or {}).get("total_trades") or 0),
            "win_rate": float((scalper_portfolio or {}).get("win_rate") or 0),
            "is_circuit_broken": bool((scalper_portfolio or {}).get("is_circuit_broken")),
        } if scalper_portfolio else None
    except Exception:
        db_state["scalper_portfolio"] = None

    try:
        # Active titulars
        if scalper_run:
            titulars = db.list_scalper_pool(status="ACTIVE_TITULAR", run_id=scalper_run)
            db_state["active_titulars"] = len(titulars)
            db_state["titular_wallets"] = [
                {
                    "wallet": t["wallet_address"][:10] + "...",
                    "types": t.get("approved_market_types", []),
                    "score": t.get("composite_score"),
                }
                for t in titulars
            ]
        else:
            db_state["active_titulars"] = 0
            db_state["titular_wallets"] = []
    except Exception:
        db_state["active_titulars"] = 0
        db_state["titular_wallets"] = []

    try:
        # Enriched profiles count
        profiles = db.list_wallet_profiles(limit=1)
        # Use a rough count (the list function returns limited rows)
        db_state["enriched_profiles_sample"] = len(profiles)
    except Exception:
        db_state["enriched_profiles_sample"] = 0

    # ── Modules ─────────────────────────────────────────────
    modules = [
        {"name": "profile_enricher.py", "desc": "Enriquece perfiles de wallets con 45+ KPIs cada 90s"},
        {"name": "pool_selector.py", "desc": "Selecciona 4 titulares desde wallet_profiles por composite score"},
        {"name": "copy_monitor.py", "desc": "Copia trades de titulares filtrando por tipo de mercado aprobado"},
        {"name": "scalper_executor.py", "desc": "Ejecuta trades con sizing relativo al portfolio (autocompounding)"},
        {"name": "rotation_engine.py", "desc": "Health-check cada 72h, rota solo por degradacion"},
        {"name": "portfolio_sizer.py", "desc": "Calcula tamano de posicion como % de la asignacion del titular"},
        {"name": "titular_risk.py", "desc": "Configura CB individual adaptativo al HR de cada trader"},
        {"name": "cooldown_manager.py", "desc": "Gestiona cooldowns 30/60/90 dias con escalacion"},
        {"name": "slot_orchestrator.py", "desc": "Orquestador de slots por universo para Specialist Edge"},
        {"name": "position_manager.py", "desc": "Trailing stop + deteccion de resolucion para Specialist"},
        {"name": "risk_manager_ct.py", "desc": "Circuit breaker global y drawdown ATH para ambas estrategias"},
        {"name": "market_type_classifier.py", "desc": "Clasifica mercados en ~20 tipos via regex (0 API calls)"},
    ]

    services = [
        {"name": "polymarket-specialist", "desc": "Estrategia Specialist Edge (daemon)"},
        {"name": "polymarket-profile-enricher", "desc": "Enriquecedor de perfiles (daemon, batch 3 cada 90s)"},
        {"name": "polymarket-roadmap-updater", "desc": "Actualizacion diaria del roadmap (timer 06:00 UTC)"},
    ]

    return {
        "generated_at": now_ts,
        "specialist_config": specialist_config,
        "scalper_config": scalper_config,
        "risk_config": risk_config,
        "db_state": db_state,
        "modules": modules,
        "services": services,
        "paper_mode": C.PAPER_MODE,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate roadmap snapshot")
    parser.add_argument("--once", action="store_true", help="Generate once and exit")
    args = parser.parse_args()

    logger.info("Generating roadmap snapshot...")
    snapshot = _build_snapshot()
    db.insert_roadmap_snapshot(snapshot, version="v2.0-scalper-v2")
    logger.info("Roadmap snapshot saved successfully")

    if not args.once:
        logger.info("Roadmap updater: snapshot generated. Exiting (timer will re-trigger).")


if __name__ == "__main__":
    main()
