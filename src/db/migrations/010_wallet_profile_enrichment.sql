-- ============================================================
-- Wallet Profile Enrichment — dual-strategy wallet profiles
-- Run in Supabase SQL Editor: https://supabase.com/dashboard/project/pdmmvhshorwfqseattvz/sql
-- ============================================================
--
-- Agnostic table: enriches wallets regardless of which strategy detected them.
-- Sources: spec_ranking (SPECIALIST) + scalper_pool (SCALPER).
-- A wallet present in both strategies has a single profile row with badges.
--
-- Fields are grouped in "bloques" matching docs/profile_enricher_design.md.
-- Many fields are intentionally nullable: the MVP populates ~45 fields and
-- defers the rest to Phase 2 (requires endDate cross-reference) or Phase 3
-- (market price at entry).

CREATE TABLE IF NOT EXISTS wallet_profiles (
    -- Bloque 0: Control y contexto de estrategia
    wallet                            TEXT PRIMARY KEY,
    enriched_at                       BIGINT NOT NULL,
    enrichment_version                INTEGER NOT NULL DEFAULT 1,
    data_completeness_pct             REAL,
    profile_confidence                TEXT,                          -- LOW / MEDIUM / HIGH
    trades_analyzed                   INTEGER,
    positions_analyzed                INTEGER,
    analysis_window_days              INTEGER,
    stale_after_days                  INTEGER DEFAULT 7,
    priority_score                    REAL,

    -- Dual-strategy context
    strategies_active                 TEXT[] DEFAULT ARRAY[]::TEXT[],
    specialist_score                  REAL,
    scalper_rank                      INTEGER,
    scalper_status                    TEXT,
    detected_by_specialist_at         BIGINT,
    detected_by_scalper_at            BIGINT,

    -- Bloque extra: Clasificación de arquetipo (Hearthstone-style)
    primary_archetype                 TEXT,                          -- HODLER / EDGE_HUNTER / SPECIALIST / GENERALIST / WHALE / SCALPER_PROFILE / BOT / MOMENTUM_CHASER
    archetype_confidence              REAL,                          -- 0.0-1.0 strength of match
    archetype_traits                  TEXT[] DEFAULT ARRAY[]::TEXT[], -- HOT / COLD / CONTRARIAN / DISCIPLINED
    rarity_tier                       TEXT,                          -- LEGENDARY / EPIC / RARE / COMMON

    -- Bloque 1: Cobertura y transferibilidad
    primary_universe                  TEXT,
    active_universes                  TEXT[],
    universe_hit_rates                JSONB,
    universe_profit_factors           JSONB,
    universe_trade_counts             JSONB,
    cross_universe_alpha              REAL,
    domain_expertise_breadth          INTEGER,
    best_market_type                  TEXT,
    best_type_hit_rate                REAL,
    best_type_profit_factor           REAL,
    type_hit_rates                    JSONB,
    type_profit_factors               JSONB,
    type_trade_counts                 JSONB,
    domain_agnostic_score             REAL,
    type_transfer_matrix              JSONB,                         -- Deferred Phase 2

    -- Bloque 2: Timing de entrada (Deferred Phase 2 — requires endDate per trade)
    avg_hours_to_resolution_at_entry  REAL,
    p25_hours_to_resolution           REAL,
    early_entry_pct                   REAL,
    late_entry_pct                    REAL,
    market_age_preference             TEXT,
    avg_entry_price_winners           REAL,
    avg_entry_price_losers            REAL,
    contrarian_score                  REAL,
    entry_edge_score                  REAL,

    -- Bloque 3: Gestión de salidas (MVP computes only hold_to_resolution_pct)
    hold_to_resolution_pct            REAL,
    avg_exit_hours_before_resolution  REAL,
    early_exit_on_winners_pct         REAL,
    early_exit_on_losers_pct          REAL,
    avg_exit_price_winners            REAL,
    avg_realized_vs_max_roi           REAL,
    stop_loss_rate                    REAL,
    profit_taking_rate                REAL,
    exit_quality_score                REAL,

    -- Bloque 4: Sizing y convicción
    avg_position_size_usd             REAL,
    median_position_size_usd          REAL,
    position_size_cv                  REAL,
    size_conviction_ratio             REAL,
    max_position_pct_of_portfolio     REAL,
    concentration_gini                REAL,
    estimated_portfolio_usd           REAL,
    typical_n_simultaneous            REAL,
    max_simultaneous_positions        INTEGER,
    avg_capital_deployed_pct          REAL,

    -- Bloque 5: Portfolio
    universe_allocation               JSONB,
    market_diversification_score      REAL,
    drawdown_response                 TEXT,                          -- Deferred
    win_streak_response               TEXT,                          -- Deferred
    avg_portfolio_turnover_days       REAL,
    max_drawdown_estimated_pct        REAL,
    recovery_speed_score              REAL,                          -- Deferred
    sharpe_proxy                      REAL,

    -- Bloque 6: Temporales y actividad reciente
    preferred_hour_utc                INTEGER,
    active_hours_spread               INTEGER,
    weekend_activity_ratio            REAL,
    activity_burst_pattern            BOOLEAN,
    last_30d_trades                   INTEGER,
    last_7d_trades                    INTEGER,
    momentum_score                    REAL,
    hit_rate_trend                    TEXT,                          -- IMPROVING / STABLE / DECLINING
    hit_rate_last_30d                 REAL,
    hit_rate_variance                 REAL,
    worst_30d_hit_rate                REAL,

    -- Bloque 7: Calidad de señal (Deferred Phase 3 — requires market prices at entry)
    independent_signal_score          REAL,
    smart_money_correlation           REAL,
    consensus_follower_score          REAL,
    avg_implied_edge_at_entry         REAL,

    -- Bloque 8: Raw storage
    full_analysis                     JSONB,
    notes                             TEXT
);

-- Core indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_wallet_profiles_priority
    ON wallet_profiles (priority_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_confidence_enriched
    ON wallet_profiles (profile_confidence, enriched_at DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_strategies_gin
    ON wallet_profiles USING gin (strategies_active);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_universe
    ON wallet_profiles (primary_universe, best_type_hit_rate DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_archetype
    ON wallet_profiles (primary_archetype, rarity_tier);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_stale
    ON wallet_profiles (enriched_at, stale_after_days);
