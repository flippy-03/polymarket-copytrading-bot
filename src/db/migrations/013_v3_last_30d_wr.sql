-- v3.0 — Recent-window actual win rate (last 30 days).
-- Used by pool_selector to skip titulars whose enricher HR diverges sharply
-- from recent real performance (protects against stale inflated metrics).
ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS last_30d_actual_wr REAL;
