-- shadow_trades: parallel tracking of signals that couldn't be executed
-- due to capacity constraints (MAX_OPEN_POSITIONS, circuit_breaker, max_drawdown).
--
-- Purpose: separate signal quality validation (shadow_trades) from
-- pipeline mechanics validation (paper_trades).
--
-- Run this in Supabase Dashboard → SQL Editor.

CREATE TABLE IF NOT EXISTS shadow_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID REFERENCES signals(id) ON DELETE SET NULL,
    market_id       UUID NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('YES', 'NO')),
    entry_price     DECIMAL(10,4) NOT NULL,
    entry_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    blocked_reason  TEXT,          -- why it wasn't executed (e.g. max_open_positions)
    exit_price      DECIMAL(10,4),
    exit_at         TIMESTAMPTZ,
    close_reason    TEXT,          -- RESOLUTION / TRAILING_STOP / TAKE_PROFIT / TIMEOUT
    pnl_usd         DECIMAL(10,2),
    pnl_pct         DECIMAL(8,4),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    run_id          INT
);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_status   ON shadow_trades(status);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_market   ON shadow_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_signal   ON shadow_trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_entry_at ON shadow_trades(entry_at DESC);
