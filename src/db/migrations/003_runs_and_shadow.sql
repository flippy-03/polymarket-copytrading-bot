-- ============================================================
-- Polymarket Copytrading Bot — Runs + Shadow trades + Raw data
-- Migration 003. Non-destructive: only CREATE / ALTER / INSERT.
-- Run in Supabase SQL Editor after 002_copytrading.sql.
-- ============================================================

-- ---------- runs: versioning checkpoints per strategy ----------
CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy TEXT NOT NULL,              -- BASKET | SCALPER
    version TEXT NOT NULL,               -- e.g. "v1.0-initial-backtest"
    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | CLOSED | ARCHIVED
    parent_run_id UUID REFERENCES runs(id),  -- set when this run is a recalculation derived from another
    started_at TIMESTAMP DEFAULT now(),
    ended_at TIMESTAMP,
    notes TEXT,
    config_snapshot JSONB,
    UNIQUE (strategy, version)
);

-- Idempotent guard: if `runs` existed from a previous partial migration, ensure
-- every column above is present before we index/insert against it.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS version TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ACTIVE';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS parent_run_id UUID REFERENCES runs(id);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP DEFAULT now();
ALTER TABLE runs ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS config_snapshot JSONB;
UPDATE runs SET status = 'ACTIVE' WHERE status IS NULL;
ALTER TABLE runs ALTER COLUMN status SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_one_active_per_strategy
    ON runs(strategy) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_runs_strategy_status ON runs(strategy, status);

-- ---------- Seed initial runs for BASKET and SCALPER ----------
INSERT INTO runs (strategy, version, status, notes)
VALUES
    ('BASKET', 'v1.0-initial-backtest', 'ACTIVE',
     'Initial paper backtest — baseline before any tuning'),
    ('SCALPER', 'v1.0-initial-backtest', 'ACTIVE',
     'Initial paper backtest — baseline before any tuning')
ON CONFLICT (strategy, version) DO NOTHING;

-- ============================================================
-- Attach run_id to strategy-derived tables (empty tables: NOT NULL is safe)
-- ============================================================

ALTER TABLE copy_trades
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE copy_trades
    ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE consensus_signals
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE consensus_signals
    ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE wallet_metrics
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE wallet_metrics
    ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE rotation_history
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE rotation_history
    ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE basket_wallets
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE basket_wallets
    ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE scalper_pool
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT;
ALTER TABLE scalper_pool
    ALTER COLUMN run_id SET NOT NULL;

-- Widen membership uniqueness to include run_id so the same wallet can appear
-- in multiple runs (historic + active) without violating constraints.
ALTER TABLE basket_wallets
    DROP CONSTRAINT IF EXISTS basket_wallets_basket_id_wallet_address_key;
ALTER TABLE basket_wallets
    ADD CONSTRAINT basket_wallets_run_basket_wallet_key
    UNIQUE (run_id, basket_id, wallet_address);

ALTER TABLE scalper_pool
    DROP CONSTRAINT IF EXISTS scalper_pool_wallet_address_key;
ALTER TABLE scalper_pool
    ADD CONSTRAINT scalper_pool_run_wallet_key
    UNIQUE (run_id, wallet_address);

-- Helpful run-scoped indexes
CREATE INDEX IF NOT EXISTS idx_copy_trades_run ON copy_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_consensus_signals_run ON consensus_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_wallet_metrics_run ON wallet_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_rotation_history_run ON rotation_history(run_id);
CREATE INDEX IF NOT EXISTS idx_basket_wallets_run ON basket_wallets(run_id);
CREATE INDEX IF NOT EXISTS idx_scalper_pool_run ON scalper_pool(run_id);

-- ============================================================
-- Shadow trades: flag + dual close columns on copy_trades
-- ============================================================
-- Real trades use the original entry_price/exit_price/pnl_usd/pnl_pct/close_reason.
-- Shadow trades ALSO write to those columns (= "stops" outcome) AND populate the
-- "pure" columns (no stops, held to resolution). This way queries that aggregate
-- PnL by strategy keep working unchanged and we get the pure-signal metric "for
-- free" on shadow rows only.

ALTER TABLE copy_trades
    ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE copy_trades
    ADD COLUMN IF NOT EXISTS exit_price_pure NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS pnl_pure_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS pnl_pure_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS closed_at_pure TIMESTAMP,
    ADD COLUMN IF NOT EXISTS close_reason_pure TEXT;  -- RESOLUTION | TIMEOUT

CREATE INDEX IF NOT EXISTS idx_copy_trades_shadow_strategy
    ON copy_trades(strategy, is_shadow, status);
CREATE INDEX IF NOT EXISTS idx_copy_trades_shadow_open
    ON copy_trades(strategy, is_shadow) WHERE status = 'OPEN';

-- ============================================================
-- portfolio_state_ct: promote to (strategy, run_id, is_shadow) key
-- ============================================================

ALTER TABLE portfolio_state_ct
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES runs(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT false;

-- Backfill the two seed rows with the ACTIVE run for their strategy
UPDATE portfolio_state_ct ps
SET run_id = r.id
FROM runs r
WHERE r.strategy = ps.strategy
  AND r.status = 'ACTIVE'
  AND ps.run_id IS NULL;

ALTER TABLE portfolio_state_ct ALTER COLUMN run_id SET NOT NULL;

-- Swap primary key
ALTER TABLE portfolio_state_ct DROP CONSTRAINT IF EXISTS portfolio_state_ct_pkey;
ALTER TABLE portfolio_state_ct
    ADD CONSTRAINT portfolio_state_ct_pkey
    PRIMARY KEY (strategy, run_id, is_shadow);

-- Seed shadow portfolio rows (one per strategy, same run as the real row)
INSERT INTO portfolio_state_ct
    (strategy, run_id, is_shadow, initial_capital, current_capital, max_open_positions)
SELECT
    r.strategy,
    r.id,
    true,
    1000,
    1000,
    CASE WHEN r.strategy = 'BASKET' THEN 8 ELSE 5 END
FROM runs r
WHERE r.status = 'ACTIVE'
ON CONFLICT (strategy, run_id, is_shadow) DO NOTHING;

-- ============================================================
-- Raw data tables (immutable, no run_id — reused across runs for recalculation)
-- ============================================================

-- observed_trades: every trade we see on a tracked wallet (polled from data-api)
CREATE TABLE IF NOT EXISTS observed_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    tx_hash TEXT,                         -- when available, used as dedupe
    observed_at TIMESTAMP DEFAULT now(),  -- when we recorded the trade
    traded_at TIMESTAMP,                  -- when the trade actually happened on-chain

    market_polymarket_id TEXT NOT NULL,
    market_question TEXT,
    outcome_token_id TEXT,
    outcome_label TEXT,                   -- "Yes" / "No" / raw string from API
    direction TEXT,                       -- YES | NO (normalized)
    side TEXT,                            -- BUY | SELL

    price NUMERIC(8,6),
    size NUMERIC,                         -- shares
    usdc_size NUMERIC,                    -- notional

    raw JSONB                             -- full API payload for replay
);

CREATE INDEX IF NOT EXISTS idx_observed_trades_wallet_time
    ON observed_trades(wallet_address, traded_at DESC);
CREATE INDEX IF NOT EXISTS idx_observed_trades_market
    ON observed_trades(market_polymarket_id, traded_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_observed_trades_dedupe
    ON observed_trades(wallet_address, tx_hash, outcome_token_id)
    WHERE tx_hash IS NOT NULL;

-- market_price_snapshots: CLOB midpoint samples used for PnL/recalculation
CREATE TABLE IF NOT EXISTS market_price_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outcome_token_id TEXT NOT NULL,
    market_polymarket_id TEXT,
    snapshot_at TIMESTAMP DEFAULT now(),
    price NUMERIC(8,6) NOT NULL,
    best_bid NUMERIC(8,6),
    best_ask NUMERIC(8,6),
    liquidity_usd NUMERIC,
    source TEXT DEFAULT 'CLOB'
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_token_time
    ON market_price_snapshots(outcome_token_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_snapshots_market_time
    ON market_price_snapshots(market_polymarket_id, snapshot_at DESC);

-- wallet_position_snapshots: periodic full holdings of tracked wallets
CREATE TABLE IF NOT EXISTS wallet_position_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    snapshot_at TIMESTAMP DEFAULT now(),
    total_value_usd NUMERIC,
    position_count INTEGER,
    positions JSONB NOT NULL              -- [{asset, size, value_usd, avg_price, market_question, ...}]
);

CREATE INDEX IF NOT EXISTS idx_position_snapshots_wallet_time
    ON wallet_position_snapshots(wallet_address, snapshot_at DESC);

-- ============================================================
-- Done. Verify with:
--   SELECT strategy, version, status FROM runs;
--   SELECT strategy, run_id IS NOT NULL AS has_run, is_shadow, current_capital FROM portfolio_state_ct ORDER BY strategy, is_shadow;
--   SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
-- Expected: 12 tables total (9 from 002 + runs + observed_trades + market_price_snapshots + wallet_position_snapshots).
-- ============================================================
