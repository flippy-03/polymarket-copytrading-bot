-- ============================================================
-- Specialist Edge Strategy — DB Tables
-- Run in Supabase SQL Editor: https://supabase.com/dashboard/project/pdmmvhshorwfqseattvz/sql
-- ============================================================

-- Main ranking table: up to 200 specialists per universe
CREATE TABLE IF NOT EXISTS spec_ranking (
    wallet TEXT NOT NULL,
    universe TEXT NOT NULL,
    hit_rate REAL NOT NULL DEFAULT 0,
    universe_trades INTEGER NOT NULL DEFAULT 0,
    universe_wins INTEGER NOT NULL DEFAULT 0,
    specialist_score REAL NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    last_active_ts BIGINT NOT NULL DEFAULT 0,
    avg_position_usd REAL NOT NULL DEFAULT 0,
    is_bot BOOLEAN NOT NULL DEFAULT false,
    rank_position INTEGER,
    first_seen_ts BIGINT NOT NULL DEFAULT 0,
    last_updated_ts BIGINT NOT NULL DEFAULT 0,
    last_seen_in_market TEXT,
    run_id UUID REFERENCES runs(id) ON DELETE SET NULL,
    PRIMARY KEY (wallet, universe)
);
CREATE INDEX IF NOT EXISTS idx_spec_ranking_universe_rank ON spec_ranking (universe, rank_position);
CREATE INDEX IF NOT EXISTS idx_spec_ranking_updated ON spec_ranking (last_updated_ts);

-- Index of markets where we've seen each specialist
CREATE TABLE IF NOT EXISTS spec_markets (
    wallet TEXT NOT NULL,
    universe TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    side TEXT,
    first_seen_ts BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (wallet, condition_id)
);
CREATE INDEX IF NOT EXISTS idx_spec_markets_universe ON spec_markets (universe);

-- Per-type activity for each specialist wallet
CREATE TABLE IF NOT EXISTS spec_type_activity (
    wallet TEXT NOT NULL,
    market_type TEXT NOT NULL,
    trades INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    hit_rate REAL NOT NULL DEFAULT 0,
    avg_position_usd REAL NOT NULL DEFAULT 0,
    last_active_ts BIGINT NOT NULL DEFAULT 0,
    last_30d_trades INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (wallet, market_type)
);

-- Aggregated ranking by market type (recomputed every 6h)
CREATE TABLE IF NOT EXISTS spec_market_type_rankings (
    market_type TEXT PRIMARY KEY,
    n_specialists INTEGER NOT NULL DEFAULT 0,
    avg_hit_rate REAL NOT NULL DEFAULT 0,
    top_hit_rate REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    priority_score REAL NOT NULL DEFAULT 0,
    last_updated_ts BIGINT NOT NULL DEFAULT 0
);

-- Also archive basket tables that were left over from previous strategy
-- (run separately if baskets / basket_wallets / consensus_signals still exist)
-- ALTER TABLE baskets RENAME TO baskets_archived;
-- ALTER TABLE basket_wallets RENAME TO basket_wallets_archived;
-- ALTER TABLE consensus_signals RENAME TO consensus_signals_archived;
-- ALTER TABLE baskets_archived ADD COLUMN IF NOT EXISTS archived_at timestamptz DEFAULT now();
-- ALTER TABLE basket_wallets_archived ADD COLUMN IF NOT EXISTS archived_at timestamptz DEFAULT now();
-- ALTER TABLE consensus_signals_archived ADD COLUMN IF NOT EXISTS archived_at timestamptz DEFAULT now();
