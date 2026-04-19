"""Gamma tags client + DB cache.

Fetches canonical tag slugs for a Polymarket event via
    GET https://gamma-api.polymarket.com/events/slug/{slug}?include_tag=true

Used as a fallback-enrichment layer for market_type classification: when
the regex-based classifier returns 'unclassified', we consult the tag
cache to recover the real niche. The cache is permanent (in DB table
`market_tags_cache`) so we only hit Gamma once per event.

IMPORTANT: this module is called from the offline enrichment path
(profile_enricher, pool_selector seed), not from the bot hot path.
The scalper_executor / trade_executor keep using the sync regex classifier
for low latency.
"""
from __future__ import annotations

from typing import Optional

import requests

from src.db import supabase_client as _db
from src.utils.logger import logger


GAMMA_EVENTS_API = "https://gamma-api.polymarket.com/events/slug"

# Tag-slug → our market_type category. Built from empirical observation of
# Gamma tags seen in v2.x runs. Extend as we encounter new niches.
# Priority order: more specific first (a market tagged both "weather" and
# "daily-temperature" should resolve to weather regardless).
TAG_TO_TYPE: dict[str, str] = {
    # ── Weather ────────────────────────────────────────────────────
    "weather": "weather",
    "daily-temperature": "weather",
    "highest-temperature": "weather",
    "lowest-temperature": "weather",
    "hurricanes": "weather",
    "earthquakes": "weather",
    "wildfire": "weather",
    "climate": "weather",

    # ── Sports / NFL / NBA / tennis ────────────────────────────────
    "nfl": "sports_winner",
    "super-bowl": "sports_winner",
    "american-football": "sports_winner",
    "nba": "sports_winner",
    "basketball": "sports_winner",
    "tennis": "sports_winner",
    "wta": "sports_winner",
    "atp": "sports_winner",
    "nhl": "sports_winner",
    "hockey": "sports_winner",
    "mlb": "sports_winner",
    "baseball": "sports_winner",
    "soccer": "sports_winner",
    "epl": "sports_winner",

    # ── Crypto price ───────────────────────────────────────────────
    "bitcoin": "crypto_above",
    "ethereum": "crypto_above",
    "crypto-prices": "crypto_above",

    # ── Politics ───────────────────────────────────────────────────
    "elections": "politics_election",
    "congress": "politics_legislative",

    # ── Other categorical ──────────────────────────────────────────
    "mentions": "mentions",
    "pop-culture": "mentions",
    "twitter-mentions": "mentions",

    # ── Macro / economics ──────────────────────────────────────────
    "fed-rates": "econ_fed_rates",
    "inflation": "econ_data",
    "cpi": "econ_data",
}

# In-memory LRU-ish cache (dict — small enough that we don't need OrderedDict).
_mem_cache: dict[str, tuple[list[str], Optional[str]]] = {}
_MAX_MEM = 2000


def _fetch_gamma_tags(event_slug: str) -> Optional[list[str]]:
    """Hit Gamma API for a single event's tags. Returns list of tag slugs
    or None on error. The caller decides what to do on None.
    """
    try:
        r = requests.get(
            f"{GAMMA_EVENTS_API}/{event_slug}",
            params={"include_tag": "true"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        tags = data.get("tags") or []
        return [t.get("slug") for t in tags if t.get("slug")]
    except Exception as e:
        logger.debug(f"gamma_tags fetch {event_slug}: {e}")
        return None


def _niche_from_tags(tag_slugs: list[str]) -> Optional[str]:
    """Map the first matching tag slug to our market_type category."""
    for slug in tag_slugs:
        if slug in TAG_TO_TYPE:
            return TAG_TO_TYPE[slug]
    return None


def _cache_get_db(event_slug: str) -> Optional[tuple[list[str], Optional[str]]]:
    """Look up cached tags in DB. Returns (tag_slugs, niche) or None if miss."""
    try:
        client = _db.get_client()
        row = (
            client.table("market_tags_cache")
            .select("tag_slugs,niche")
            .eq("event_slug", event_slug)
            .limit(1)
            .execute()
            .data
        )
        if row:
            tags = row[0].get("tag_slugs") or []
            niche = row[0].get("niche")
            return tags, niche
    except Exception as e:
        logger.debug(f"cache_get_db {event_slug}: {e}")
    return None


def _cache_put_db(event_slug: str, tag_slugs: list[str], niche: Optional[str]) -> None:
    try:
        client = _db.get_client()
        client.table("market_tags_cache").upsert(
            {
                "event_slug": event_slug,
                "tag_slugs": tag_slugs,
                "niche": niche,
            },
            on_conflict="event_slug",
        ).execute()
    except Exception as e:
        logger.debug(f"cache_put_db {event_slug}: {e}")


def get_niche_for_event(event_slug: str) -> Optional[str]:
    """Resolve a market niche via Gamma tags, cache-first.

    Returns the mapped market_type string (e.g. 'weather', 'sports_winner')
    or None if the event has no recognised tag. Safe on network errors —
    returns whatever the cache has or None.
    """
    if not event_slug:
        return None

    # 1. In-memory cache
    if event_slug in _mem_cache:
        return _mem_cache[event_slug][1]

    # 2. DB cache
    db_hit = _cache_get_db(event_slug)
    if db_hit is not None:
        tags, niche = db_hit
        _mem_cache[event_slug] = (tags, niche)
        return niche

    # 3. Gamma API
    tags = _fetch_gamma_tags(event_slug)
    if tags is None:
        return None   # network error — don't cache to allow retry later

    niche = _niche_from_tags(tags)
    _cache_put_db(event_slug, tags, niche)
    if len(_mem_cache) < _MAX_MEM:
        _mem_cache[event_slug] = (tags, niche)
    return niche


def classify_via_tags(market: dict) -> Optional[str]:
    """Convenience: given a market dict (with eventSlug or events[0].slug),
    return the Gamma-tag-derived niche or None.

    Use this as a fallback when the regex classifier yields 'unclassified'.
    """
    event_slug = market.get("eventSlug") or market.get("event_slug")
    if not event_slug:
        events_list = market.get("events") or []
        if isinstance(events_list, list) and events_list:
            first = events_list[0] or {}
            if isinstance(first, dict):
                event_slug = first.get("slug")
    if not event_slug:
        return None
    return get_niche_for_event(event_slug)
