-- Enricher v2: avg_hold_time_minutes, type_avg_hold_minutes, hr_cashpnl_confirmed_pct
-- Adds metrics to detect HFT scalpers (hold < 5min) and measure HR data quality.

ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS avg_hold_time_minutes REAL,
    ADD COLUMN IF NOT EXISTS type_avg_hold_minutes JSONB,
    ADD COLUMN IF NOT EXISTS hr_cashpnl_confirmed_pct REAL;

-- Index to quickly filter out scalper bots in pool selection queries
CREATE INDEX IF NOT EXISTS idx_wallet_profiles_hold_time
    ON wallet_profiles(avg_hold_time_minutes)
    WHERE avg_hold_time_minutes IS NOT NULL;
