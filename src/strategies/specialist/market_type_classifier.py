"""
Market type classifier for Specialist Edge.

Classifies any market dict (from Gamma API) into one of ~20 structural types
using regex patterns on question/slug/eventSlug. The classification is purely
local (0 API requests) and runs in <1ms per market.
"""
import re
from typing import Optional


# ── Pattern → type mapping (order matters — first match wins) ──────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ── Financial markets (must run before crypto — gold/silver match crypto_above otherwise)
    (re.compile(
        r"\b(s&p\s*500?|nasdaq|dow\s*jones|ftse|dax|nikkei|hang\s*seng|russell\s*2000|vix)\b",
        re.I,
    ), "financial_index"),
    (re.compile(
        r"\b(gold|silver|crude\s*oil|brent|wti|natural\s*gas|copper|platinum)\b.{0,30}\$[\d,]+",
        re.I,
    ), "financial_commodity"),
    (re.compile(
        r"\b(stock|share|equity)\b.{0,30}\b(close|closing|above|below)\b.{0,20}\$[\d,]+",
        re.I,
    ), "financial_stock"),

    # ── Crypto directional: above / below / hit-price ────────────────────────
    (re.compile(
        r"\b(above|over|exceed|higher than|break above)\b.{0,40}\$[\d,k]+",
        re.I,
    ), "crypto_above"),
    (re.compile(
        r"\b(below|under|drop below|fall below|lower than)\b.{0,40}\$[\d,k]+",
        re.I,
    ), "crypto_below"),
    (re.compile(
        r"\b(between|range|within)\b.{0,60}\$[\d,k]+.{0,20}\$[\d,k]+",
        re.I,
    ), "crypto_price_range"),
    (re.compile(
        r"\b(hit|reach|touch|peak at)\b.{0,40}\$[\d,k]+",
        re.I,
    ), "crypto_hit_price"),
    # Micro-timeframe first (5/10-min windows) — must match before _short/_daily
    # to avoid being absorbed by broader patterns. These are near-random for
    # copy-trading: the system's latency alone destroys any edge.
    (re.compile(
        r"\b(up|down)\b.{0,40}\b([1-9]|1[0-4])[\s-]*(?:min(?:ute)?s?|m\b)",
        re.I,
    ), "crypto_updown_micro"),
    (re.compile(
        r"\b(up|down)\b.{0,20}\b(15[\s-]*min|30[\s-]*min|1[\s-]*h|4[\s-]*h)\b",
        re.I,
    ), "crypto_updown_short"),
    (re.compile(
        r"\b(up|down|higher|lower)\b.{0,40}\b(today|daily|24h|24-hour|end of day)\b",
        re.I,
    ), "crypto_updown_daily"),
    # Generic "Up or Down" title with time window (no dollar sign)
    # "Bitcoin Up or Down - April 19, 6:25AM-6:30AM" → crypto_updown_micro
    (re.compile(
        r"\b(bitcoin|btc|ethereum|eth|sol|solana)\s+up\s+or\s+down\b.*\d+(?::\d+)?\s*(?:am|pm)?\s*-\s*\d+(?::\d+)?",
        re.I,
    ), "crypto_updown_micro"),

    # ── Sports ───────────────────────────────────────────────────────────────
    (re.compile(
        r"\b(nba|nhl|nfl|mlb|nba|mls|wnba|ncaa|super bowl|playoffs|finals)\b",
        re.I,
    ), "sports_winner"),
    (re.compile(
        r"\bcover the spread\b|\bATS\b|\bpoints? spread\b",
        re.I,
    ), "sports_spread"),
    (re.compile(
        r"\b(over|under)\b.{0,20}\b(\d+\.?\d*)\s*(points?|goals?|runs?|total)\b",
        re.I,
    ), "sports_total"),
    (re.compile(
        r"\b(champion|championship|mvp|cy young|rookie of the year|win the)\b",
        re.I,
    ), "sports_futures"),

    # ── Politics ─────────────────────────────────────────────────────────────
    (re.compile(
        r"\b(election|electoral|primary|vote|ballot|candidate|polling|win the (state|county|district))\b",
        re.I,
    ), "politics_election"),
    (re.compile(
        r"\b(pass|vote on|senate|house|congress|legislation|bill|filibuster|amendment)\b",
        re.I,
    ), "politics_legislative"),
    (re.compile(
        r"\b(executive order|veto|pardon|nominate|appoint|resign|impeach)\b",
        re.I,
    ), "politics_executive"),
    (re.compile(
        r"\b(poll|approval rating|favorability|survey)\b",
        re.I,
    ), "politics_polls"),

    # ── Economics ────────────────────────────────────────────────────────────
    (re.compile(
        r"\b(fed(eral reserve)?|fomc|interest rate|rate hike|rate cut|basis point|bps)\b",
        re.I,
    ), "econ_fed_rates"),
    (re.compile(
        r"\b(cpi|inflation|gdp|unemployment|jobless|nonfarm|payroll|pce|ppi|retail sales)\b",
        re.I,
    ), "econ_data"),

    # ── Other specific ───────────────────────────────────────────────────────
    (re.compile(r"\b(temperature|rain|snow|hurricane|weather|celsius|fahrenheit)\b", re.I), "weather"),
    (re.compile(r"\b(apple|google|microsoft|tesla|amazon|openai|ai model|chatgpt)\b", re.I), "tech"),
    (re.compile(r"\b(oscar|emmy|grammy|box office|film|movie|song|chart)\b", re.I), "culture"),
]


def classify(market: dict) -> str:
    """
    Classify a market dict into a structural type string.

    Uses (in order): question, slug, eventSlug, eventTitle.
    Returns 'other' if no pattern matches.
    """
    # Activity API dicts use "title" instead of "question"; Gamma dicts use "question".
    # We fall back to "title" so the classifier works in both contexts.
    question_or_title = market.get("question") or market.get("title") or ""
    text = " ".join(filter(None, [
        question_or_title,
        market.get("slug") or "",
        market.get("eventSlug") or "",
        market.get("eventTitle") or "",
        market.get("description") or "",
    ]))

    for pattern, mtype in _PATTERNS:
        if pattern.search(text):
            return mtype

    # Heuristic: if the slug/question mentions a crypto ticker + price, try again
    if re.search(r"\b(btc|bitcoin|eth|ethereum|sol|solana|xrp|doge|avax|bnb)\b", text, re.I):
        if re.search(r"\$[\d,k]+", text):
            return "crypto_above"  # generic directional fallback

    # Explicit unclassified bucket so downstream code can block it without
    # colliding with legitimate "other" markets someone might whitelist.
    return "unclassified"


def classify_batch(markets: list[dict]) -> dict[str, str]:
    """
    Classify a list of markets in one call.
    Returns {conditionId: market_type} for markets that have a conditionId.
    """
    return {
        m["conditionId"]: classify(m)
        for m in markets
        if m.get("conditionId")
    }
