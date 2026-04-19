-- v3.1 — niche_concentration_pct: % of resolved trades in the single best
-- market type. Used as a soft penalty in pool_selector composite_score to
-- favor specialists over generalists (niche_specialist_engine.html §02).
ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS niche_concentration_pct REAL;

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_niche_conc
    ON wallet_profiles(niche_concentration_pct)
    WHERE niche_concentration_pct IS NOT NULL;
