-- ============================================================
-- Polymarket Copytrading Bot — Risk controls enhancements
-- Migration 005. Non-destructive: only ALTER / UPDATE.
-- Run in Supabase SQL Editor after 004_widen_metric_columns.sql.
-- ============================================================

-- peak_capital: All-Time High portfolio value — used for ATH-based drawdown.
-- Initialised to initial_capital for existing rows.
ALTER TABLE portfolio_state_ct
    ADD COLUMN IF NOT EXISTS peak_capital NUMERIC(14,2);

UPDATE portfolio_state_ct
    SET peak_capital = initial_capital
    WHERE peak_capital IS NULL;

-- requires_manual_review: when TRUE the circuit breaker does NOT auto-reset
-- after the timer expires — the operator must call manual_resume() explicitly.
-- Set automatically on consecutive-loss trips and on manual stops from dashboard.
ALTER TABLE portfolio_state_ct
    ADD COLUMN IF NOT EXISTS requires_manual_review BOOLEAN DEFAULT false;
