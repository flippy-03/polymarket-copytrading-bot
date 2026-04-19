-- v3.1 — Permanent cache of Gamma event tags → market_type classification.
--
-- The regex-based market_type_classifier works for 90%+ of markets but
-- misses edge cases (very recent markets, non-English titles, multi-outcome
-- events where the title doesn't carry the topic). When it yields
-- 'unclassified', we fall back to Gamma's canonical tags via
-- /events/slug/{slug}?include_tag=true, cached here to avoid repeat calls.
CREATE TABLE IF NOT EXISTS market_tags_cache (
    event_slug    TEXT PRIMARY KEY,
    tag_slugs     JSONB NOT NULL DEFAULT '[]',
    niche         TEXT,                              -- mapped market_type or NULL
    cached_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_tags_cache_niche
    ON market_tags_cache(niche)
    WHERE niche IS NOT NULL;
