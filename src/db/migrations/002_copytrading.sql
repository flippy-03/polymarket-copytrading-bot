-- ============================================================
-- Polymarket Copytrading Bot — Schema Migration
-- Run in Supabase SQL Editor AFTER backing up 001 data.
-- Drops all contrarian tables and creates the copytrading schema.
-- ============================================================

-- ---------- DROP contrarian schema (001) ----------
DROP TABLE IF EXISTS shadow_trades CASCADE;
DROP TABLE IF EXISTS watched_wallets CASCADE;
DROP TABLE IF EXISTS portfolio_state CASCADE;
DROP TABLE IF EXISTS paper_trades CASCADE;
DROP TABLE IF EXISTS signals CASCADE;
DROP TABLE IF EXISTS market_snapshots CASCADE;
DROP TABLE IF EXISTS markets CASCADE;

-- ============================================================
-- COPYTRADING SCHEMA
-- ============================================================

-- ---------- wallets: master registry of tracked wallets ----------
CREATE TABLE wallets (
    address TEXT PRIMARY KEY,
    first_seen TIMESTAMP DEFAULT now(),
    last_analyzed TIMESTAMP,
    is_quarantined BOOLEAN DEFAULT false,
    quarantine_until TIMESTAMP,
    quarantine_reason TEXT,            -- BOT_DETECTED | LOSS_STREAK | MANUAL
    notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_wallets_quarantine ON wallets(is_quarantined, quarantine_until);

-- ---------- wallet_metrics: historical snapshots of wallet metrics ----------
CREATE TABLE wallet_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    snapshot_at TIMESTAMP DEFAULT now(),

    -- Tier 1
    win_rate NUMERIC(6,4),
    total_trades INTEGER,
    track_record_days INTEGER,
    avg_holding_days NUMERIC(6,2),
    trades_per_month NUMERIC(6,2),
    pnl_30d NUMERIC,
    pnl_7d NUMERIC,
    tier1_pass BOOLEAN,

    -- Tier 2
    profit_factor NUMERIC(6,2),
    edge_vs_odds NUMERIC(6,4),
    market_categories INTEGER,
    positive_weeks_pct NUMERIC(5,4),
    avg_position_size NUMERIC,
    tier2_score INTEGER,               -- 0..6 count of filters passed

    -- Tier 3 flags
    tier3_alerts JSONB,

    -- Bot detection
    bot_interval_cv NUMERIC(6,4),
    bot_size_cv NUMERIC(6,4),
    bot_delay_correlation NUMERIC(6,4),
    bot_unique_market_pct NUMERIC(6,4),
    bot_score INTEGER,                 -- 0..5 count of tests passed
    is_bot BOOLEAN,

    -- Scalper ranking
    sharpe_14d NUMERIC(8,4),

    -- Composite basket ranking
    composite_score NUMERIC(8,4)
);

CREATE INDEX idx_wallet_metrics_wallet_time ON wallet_metrics(wallet_address, snapshot_at DESC);
CREATE INDEX idx_wallet_metrics_sharpe ON wallet_metrics(sharpe_14d DESC) WHERE sharpe_14d IS NOT NULL;

-- ---------- baskets: thematic groupings (Basket Consensus strategy) ----------
CREATE TABLE baskets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,            -- CRYPTO | ECONOMICS | POLITICS
    status TEXT DEFAULT 'ACTIVE',      -- ACTIVE | PAUSED | ARCHIVED
    consensus_threshold NUMERIC(4,3) DEFAULT 0.80,
    time_window_hours INTEGER DEFAULT 4,
    max_capital_pct NUMERIC(5,4) DEFAULT 0.30,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE UNIQUE INDEX idx_baskets_active_category ON baskets(category) WHERE status = 'ACTIVE';

-- ---------- basket_wallets: membership + ranking inside each basket ----------
CREATE TABLE basket_wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    basket_id UUID NOT NULL REFERENCES baskets(id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    rank_score NUMERIC(8,4),
    rank_position INTEGER,
    entered_at TIMESTAMP DEFAULT now(),
    exited_at TIMESTAMP,
    exit_reason TEXT,                  -- UNDERPERFORMANCE | BOT_DETECTED | ROTATION | MANUAL
    UNIQUE (basket_id, wallet_address)
);

CREATE INDEX idx_basket_wallets_active ON basket_wallets(basket_id) WHERE exited_at IS NULL;

-- ---------- scalper_pool: pool for Scalper Rotator strategy ----------
CREATE TABLE scalper_pool (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    status TEXT NOT NULL,              -- POOL | ACTIVE_TITULAR | QUARANTINE
    sharpe_14d NUMERIC(8,4),
    rank_position INTEGER,
    capital_allocated_usd NUMERIC DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    entered_at TIMESTAMP DEFAULT now(),
    exited_at TIMESTAMP,
    exit_reason TEXT,
    UNIQUE (wallet_address)
);

CREATE INDEX idx_scalper_pool_status ON scalper_pool(status);

-- ---------- consensus_signals: signals emitted by Basket Consensus engine ----------
CREATE TABLE consensus_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    basket_id UUID NOT NULL REFERENCES baskets(id) ON DELETE CASCADE,
    market_polymarket_id TEXT NOT NULL,
    market_question TEXT,
    direction TEXT NOT NULL,           -- YES | NO
    outcome_token_id TEXT,
    consensus_pct NUMERIC(5,4),
    wallets_agreeing INTEGER,
    wallets_total INTEGER,
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    price_at_signal NUMERIC(6,4),
    status TEXT DEFAULT 'PENDING',     -- PENDING | EXECUTED | EXPIRED | REJECTED
    created_at TIMESTAMP DEFAULT now(),
    executed_at TIMESTAMP,
    rejection_reason TEXT
);

CREATE INDEX idx_consensus_signals_status ON consensus_signals(status) WHERE status = 'PENDING';
CREATE INDEX idx_consensus_signals_basket ON consensus_signals(basket_id, created_at DESC);

-- ---------- copy_trades: unified trades table (BASKET + SCALPER) ----------
CREATE TABLE copy_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy TEXT NOT NULL,            -- BASKET | SCALPER
    signal_id UUID REFERENCES consensus_signals(id),
    source_wallet TEXT REFERENCES wallets(address),

    market_polymarket_id TEXT NOT NULL,
    market_question TEXT,
    market_category TEXT,

    direction TEXT NOT NULL,           -- YES | NO
    outcome_token_id TEXT,

    entry_price NUMERIC(6,4) NOT NULL,
    exit_price NUMERIC(6,4),
    shares NUMERIC NOT NULL,
    position_usd NUMERIC NOT NULL,

    pnl_usd NUMERIC,
    pnl_pct NUMERIC,

    opened_at TIMESTAMP DEFAULT now(),
    closed_at TIMESTAMP,
    close_reason TEXT,                 -- BASKET_EXIT_CONSENSUS | SCALPER_TITULAR_EXIT | STOP_LOSS | TAKE_PROFIT | TIMEOUT | RESOLUTION | CIRCUIT_BREAKER

    status TEXT DEFAULT 'OPEN',        -- OPEN | CLOSED | CANCELLED

    is_paper BOOLEAN DEFAULT true,
    metadata JSONB
);

CREATE INDEX idx_copy_trades_strategy_status ON copy_trades(strategy, status);
CREATE INDEX idx_copy_trades_open ON copy_trades(strategy) WHERE status = 'OPEN';
CREATE INDEX idx_copy_trades_closed_time ON copy_trades(strategy, closed_at DESC) WHERE status = 'CLOSED';
CREATE INDEX idx_copy_trades_signal ON copy_trades(signal_id) WHERE signal_id IS NOT NULL;

-- ---------- rotation_history: scalper pool rotations (weekly job) ----------
CREATE TABLE rotation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rotation_at TIMESTAMP DEFAULT now(),
    reason TEXT,                       -- SCHEDULED_WEEKLY | MANUAL | UNDERPERFORMANCE
    removed_titulars JSONB,            -- [{wallet, sharpe_14d, pnl_14d}]
    new_titulars JSONB,
    pool_snapshot JSONB                -- full ranked pool at rotation time
);

CREATE INDEX idx_rotation_history_time ON rotation_history(rotation_at DESC);

-- ---------- portfolio_state_ct: per-strategy portfolio state ----------
CREATE TABLE portfolio_state_ct (
    strategy TEXT PRIMARY KEY,         -- BASKET | SCALPER

    initial_capital NUMERIC NOT NULL,
    current_capital NUMERIC NOT NULL,
    total_pnl NUMERIC DEFAULT 0,
    total_pnl_pct NUMERIC DEFAULT 0,

    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5,4) DEFAULT 0,

    max_drawdown NUMERIC DEFAULT 0,
    sharpe_ratio NUMERIC,

    consecutive_losses INTEGER DEFAULT 0,
    is_circuit_broken BOOLEAN DEFAULT false,
    circuit_broken_until TIMESTAMP,

    open_positions INTEGER DEFAULT 0,
    max_open_positions INTEGER DEFAULT 8,

    updated_at TIMESTAMP DEFAULT now()
);

-- ---------- Seed portfolio state rows ----------
INSERT INTO portfolio_state_ct (strategy, initial_capital, current_capital, max_open_positions)
VALUES
    ('BASKET', 1000, 1000, 8),
    ('SCALPER', 1000, 1000, 5)
ON CONFLICT (strategy) DO NOTHING;

-- ============================================================
-- Done. Verify with:
--   SELECT tablename FROM pg_tables WHERE schemaname = 'public';
-- ============================================================
