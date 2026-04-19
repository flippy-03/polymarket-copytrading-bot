-- v3.0 — Market-maker / negativeRisk arbitrage detection.
--
-- Wallets that operate via REDEEM+MERGE on multi-outcome markets (e.g. the
-- "ZhangMuZhi.." bot netting +$33k/day) have edge but it does not transfer
-- to copy-traders: they hold positions across ALL outcomes of an event, so
-- copying a single trade exposes the copier to the full downside. Flag them
-- so pool_selector can exclude them by default.
ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS is_market_maker BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS mm_confidence REAL,
    ADD COLUMN IF NOT EXISTS mm_signals JSONB;

-- Index for fast filtering in pool_selector / dashboard.
CREATE INDEX IF NOT EXISTS idx_wallet_profiles_is_mm
    ON wallet_profiles(is_market_maker)
    WHERE is_market_maker = TRUE;
