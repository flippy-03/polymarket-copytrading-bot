-- v3.1 — Per-titular sizing multiplier used by the degradation evaluator.
--
-- Starts at 1.0 (full sizing). The 6h cron reduces it to 0.5 when WR15
-- falls between 0.62 and 0.65, and restores to 1.0 after a clean recovery
-- streak (WR10 >= 0.70). Values outside {0.5, 1.0} are allowed for future
-- finer granularity.
ALTER TABLE scalper_pool
    ADD COLUMN IF NOT EXISTS sizing_multiplier REAL DEFAULT 1.0;

-- Risk events audit (per-titular and portfolio-level). Mirrors ns_risk_events
-- from niche_specialist_engine.html §07 but integrated into the existing
-- project rather than a separate NS Supabase.
CREATE TABLE IF NOT EXISTS risk_events (
    id             BIGSERIAL PRIMARY KEY,
    event_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id         UUID,
    layer          TEXT,                 -- '1' | '1b' | '2' | '2b' | '3'
    scope          TEXT,                 -- 'titular' | 'portfolio' | 'system'
    wallet         TEXT,                 -- nullable for portfolio events
    action         TEXT,                 -- 'pause' | 'reduce_50' | 'restore' | 'retire' | 'halt'
    trigger_metric TEXT,
    trigger_value  NUMERIC,
    notes          TEXT,
    resolved_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_risk_events_wallet_ts
    ON risk_events(wallet, event_ts DESC)
    WHERE wallet IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_risk_events_run ON risk_events(run_id, event_ts DESC);
