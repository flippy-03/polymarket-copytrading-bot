-- ============================================================
-- Migration 004 — Widen wallet_metrics numeric columns
-- ============================================================
-- profit_factor, avg_holding_days, trades_per_month were
-- NUMERIC(6,2) → max 9999.99. Very active wallets can exceed
-- that (e.g. profit_factor = 50000 for a nearly loss-free trader).
-- Change to unbounded NUMERIC. Idempotent: ALTER TYPE is safe
-- to re-run if the column is already unbounded.
-- ============================================================

ALTER TABLE wallet_metrics
    ALTER COLUMN profit_factor     TYPE NUMERIC,
    ALTER COLUMN avg_holding_days  TYPE NUMERIC,
    ALTER COLUMN trades_per_month  TYPE NUMERIC;

-- ============================================================
-- Done. Verify with:
--   SELECT column_name, data_type, numeric_precision, numeric_scale
--   FROM information_schema.columns
--   WHERE table_name = 'wallet_metrics'
--     AND column_name IN ('profit_factor','avg_holding_days','trades_per_month');
-- Expected: data_type = 'numeric', precision and scale = NULL (unbounded).
-- ============================================================
