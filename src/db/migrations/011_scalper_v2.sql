-- Migration 011: Scalper V2 — profile-based selection, per-titular risk, cooldowns
--
-- Changes:
--   1. scalper_cooldowns: hysteresis tracking per (wallet, market_type)
--   2. scalper_config: dashboard-editable parameters per run
--   3. scalper_pool extensions: approved types, composite score, per-trader risk state
--   4. copy_trades.market_type: classified type for filtering analytics
--   5. wallet_profiles.type_sharpe_ratios: per-type Sharpe from enricher
--   6. roadmap_snapshots: daily auto-updated documentation state

-- ── 1. Cooldown tracking ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scalper_cooldowns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address  TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    reason          TEXT NOT NULL,          -- SCORE_DEGRADED | CONSECUTIVE_LOSSES | INACTIVITY | DECLINING_TREND
    started_at      TIMESTAMP DEFAULT now(),
    expires_at      TIMESTAMP NOT NULL,
    escalation_level INTEGER DEFAULT 1,     -- 1=30d, 2=60d, 3=90d
    is_active       BOOLEAN DEFAULT true,
    metrics_at_removal JSONB                -- snapshot of scores at removal time
);

-- Only one active cooldown per (wallet, market_type) at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_scalper_cooldowns_active
    ON scalper_cooldowns(wallet_address, market_type) WHERE is_active = true;

-- Fast lookup for expiry checks
CREATE INDEX IF NOT EXISTS idx_scalper_cooldowns_expires
    ON scalper_cooldowns(expires_at) WHERE is_active = true;


-- ── 2. Scalper config (dashboard-editable) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS scalper_config (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES runs(id),
    config      JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP DEFAULT now(),
    UNIQUE (run_id)
);


-- ── 3. Extend scalper_pool with V2 columns ──────────────────────────────────

ALTER TABLE scalper_pool
    ADD COLUMN IF NOT EXISTS approved_market_types JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS composite_score REAL,
    ADD COLUMN IF NOT EXISTS per_trader_loss_limit INTEGER DEFAULT 4,
    ADD COLUMN IF NOT EXISTS per_trader_consecutive_losses INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS per_trader_is_broken BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS consecutive_wins INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS allocation_pct REAL DEFAULT 0.25;


-- ── 4. Add market_type to copy_trades ───────────────────────────────────────

ALTER TABLE copy_trades
    ADD COLUMN IF NOT EXISTS market_type TEXT;

-- Index for per-titular queries (used by portfolio_sizer)
CREATE INDEX IF NOT EXISTS idx_copy_trades_source_wallet_status
    ON copy_trades(source_wallet, status) WHERE source_wallet IS NOT NULL;


-- ── 5. Per-type Sharpe in wallet_profiles ───────────────────────────────────

ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS type_sharpe_ratios JSONB;


-- ── 6. Roadmap snapshots (daily auto-update) ────────────────────────────────

CREATE TABLE IF NOT EXISTS roadmap_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_at TIMESTAMP DEFAULT now(),
    content     JSONB NOT NULL,             -- structured snapshot of config + state
    version     TEXT                        -- app version tag
);

CREATE INDEX IF NOT EXISTS idx_roadmap_latest
    ON roadmap_snapshots(snapshot_at DESC);
