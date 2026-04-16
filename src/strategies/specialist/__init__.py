"""
Specialist Edge strategy — event-driven, per-universe specialist discovery.

Architecture:
- market_type_classifier: classify any market into one of ~20 types
- specialist_profiler: compute hit_rate / specialist_score per (wallet, universe)
- type_context_builder: build per-trade context (top types by hit_rate / volume)
- ranking_db: persist + query spec_ranking / spec_markets / spec_type_activity
- type_rankings: aggregate spec_market_type_rankings (priority_score)
- market_scanner: find candidate markets by type + resolution window
- specialist_analyzer: cross-reference CLOB holders with specialist DB
- signal_generator: CLEAN / CONTESTED / SKIP classification
- hybrid_router: BD-first routing with FULL_SCAN fallback
- anti_blindness: force periodic full scans to avoid DB-only tunnel vision
- trade_executor: sizing + LIMIT order via clob_exec (paper mode)
- position_manager: trailing stop (8% activation / 15% trail / -20% hard)
- slot_orchestrator: main event loop — check positions → fill slots
"""
