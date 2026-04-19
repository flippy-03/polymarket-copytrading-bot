-- v3.1 — Shadow validation window for new titulars.
--
-- Before any wallet can copy with real capital, it must first pass a
-- shadow-trading period where all its copied trades are paper-only.
-- Only after the window closes AND the paper performance meets thresholds
-- does the titular get promoted to real trading.
--
-- Fields:
--   shadow_validation_until — UTC timestamp when the shadow window ends.
--     NULL = legacy entries (backfill: set to NULL, they skip validation).
--     Future  = still in shadow; all trades forced to is_shadow=true.
--     Past    = validation expired; shadow_validator job promotes or retires.
--   validation_outcome — enum set by the validator:
--     'PENDING'   = window still open
--     'PROMOTED'  = paper performance met gates → now trading real
--     'REJECTED'  = paper performance failed → titular retired
ALTER TABLE scalper_pool
    ADD COLUMN IF NOT EXISTS shadow_validation_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_outcome TEXT
        CHECK (validation_outcome IS NULL
               OR validation_outcome IN ('PENDING', 'PROMOTED', 'REJECTED'));

CREATE INDEX IF NOT EXISTS idx_scalper_pool_shadow_until
    ON scalper_pool(shadow_validation_until)
    WHERE shadow_validation_until IS NOT NULL;
