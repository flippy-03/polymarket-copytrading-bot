-- Migration: add position_usd and shares to shadow_trades
-- Run in Supabase Dashboard → SQL Editor

ALTER TABLE shadow_trades
  ADD COLUMN IF NOT EXISTS position_usd DECIMAL(10,2),
  ADD COLUMN IF NOT EXISTS shares       DECIMAL(10,4);
