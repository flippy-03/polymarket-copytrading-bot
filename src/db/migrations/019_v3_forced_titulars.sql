-- v3.1 — Forced (manual override) titulars in scalper_pool.
--
-- A titular flagged is_forced=TRUE bypasses:
--   1. rotation_engine health-check degradation (won't be retired automatically)
--   2. pool_selector.persist_selection retire-step (won't be demoted to POOL
--      when a fresh selection runs)
--   3. copy_monitor _should_copy approved_market_types filter (copies all
--      market types — risk/CB checks still apply)
--   4. scalper_executor approved_market_types check (no force-shadow on type)
--
-- Use case: operator manually pins a wallet for evaluation outside the
-- profile-based scoring pipeline (e.g. wallet has no enriched profile yet,
-- or operator wants to test an unusual specialist over a fixed window).
--
-- Clear the flag (UPDATE … SET is_forced=FALSE) to return the titular to
-- normal lifecycle.

ALTER TABLE scalper_pool
    ADD COLUMN IF NOT EXISTS is_forced BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_scalper_pool_forced
    ON scalper_pool(run_id, is_forced) WHERE is_forced = TRUE;
