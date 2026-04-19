"""
Copytrading config — constants, thresholds and API URLs shared by both strategies.
Values come from the implementation spec (Polymarket CopyTrading/polymarket-copytrade-implementation.md).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API URLs ─────────────────────────────────────────────
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
CLOB_WSS = "wss://ws-subscriptions-clob.polymarket.com"

# ── Auth (only used when live trading is enabled) ────────
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")
POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")

# ── Execution mode ───────────────────────────────────────
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
BASKET_INITIAL_CAPITAL = float(os.getenv("BASKET_INITIAL_CAPITAL", "1000"))
SCALPER_INITIAL_CAPITAL = float(os.getenv("SCALPER_INITIAL_CAPITAL", "1000"))

# ── Tier 1 filters (elimination) ─────────────────────────
MIN_WIN_RATE = 0.50               # relaxed 0.60→0.55→0.50; allow high-volume grinders
MIN_TRADES_TOTAL = 50             # relaxed 100→50 for backtest
MIN_TRACK_RECORD_DAYS = 30        # relaxed 120→60→30; many good traders active <2mo
MAX_HOLDING_PERIOD_DAYS = 21      # relaxed 7→21; prediction markets resolve over weeks
MIN_TRADES_PER_MONTH = 4          # relaxed 8→4 for backtest
REQUIRE_POSITIVE_PNL_30D = True
PNL_30D_TOLERANCE = -5.0          # allow up to $5 negative (rounding/dust trades)
REQUIRE_NONNEGATIVE_PNL_7D = False  # relaxed: 7d window too noisy for volatile events
# All-time PnL floor (uses /positions cashPnl as source of truth, not biased activity).
# 0 rejects net-losers; set negative to allow small drawdown tolerance.
MIN_TOTAL_PNL_USD = 150.0

# ── Tier 2 filters (edge quality) ────────────────────────
MIN_PROFIT_FACTOR = 1.5
MIN_EDGE_VS_ODDS = 0.05
MIN_MARKET_CATEGORIES = 3
MIN_POSITIVE_WEEKS_PCT = 0.65
POSITION_SIZE_RANGE = (100, 10_000)
TIER2_MIN_PASS = 4

# ── Bot detection ────────────────────────────────────────
BOT_MIN_TESTS_PASS = 3          # 4 real tests now (corr_delay removed); need 3/4
BOT_INTERVAL_CV_MIN = 0.30
BOT_SIZE_CV_MIN = 0.30
BOT_MAX_CORRELATION_SCORE = 0.70
BOT_MIN_UNIQUE_MARKETS_PCT = 0.15
BOT_MAX_TRADES_PER_MONTH = 500

# ── Risk management ──────────────────────────────────────
MAX_DRAWDOWN_PCT = 0.30
DAILY_LOSS_LIMIT = 0.10
MAX_OPEN_POSITIONS = 8
MAX_PER_MARKET_PCT = 0.15
MAX_PER_TRADE_PCT = 0.10
TIMEOUT_DAYS = 7
MIN_LIQUIDITY_24H = 5_000        # lowered for backtest; raise to 50_000+ for live
MAX_SLIPPAGE = 0.05
MAX_ENTRY_DRIFT = 0.10

# ── Basket strategy ──────────────────────────────────────
BASKET_MIN_WALLETS = 5
BASKET_MAX_WALLETS = 7              # top-N target per basket (spec 5-10)
BASKET_CONSENSUS_THRESHOLD = 0.80
BASKET_TIME_WINDOW_HOURS = 4
BASKET_MAX_CAPITAL_PCT = 0.30
BASKET_EXIT_CONSENSUS = 0.50
BASKET_MONITOR_INTERVAL_SECONDS = 60
# Discovery tuning
BASKET_POOL_CANDIDATES = 80        # candidates to analyze per basket (was hardcoded 50)
BASKET_MIN_CATEGORY_PNL_PCT = 0.35 # specialist filter: ≥35% of PnL from basket category

# ── Scalper strategy (V2 — profile-based) ────────────────
SCALPER_ACTIVE_WALLETS = 4
SCALPER_POOL_SIZE = 12
SCALPER_MONITOR_INTERVAL_SECONDS = 30
SCALPER_CONSECUTIVE_LOSS_LIMIT = 6      # global CB: 6 total cross-titular losses

# V2 selection & sizing
SCALPER_MIN_HIT_RATE = 0.55             # min type HR for (wallet, market_type) pairs
SCALPER_MIN_TRADE_COUNT = 8             # min trades per type for statistical significance
SCALPER_TRADE_PCT = 0.15                # 15% of titular allocation per trade
SCALPER_MAX_TRADE_PCT = 0.25            # max 25% of allocation on single trade
SCALPER_MIN_PER_TRADE = 5               # floor in USD
SCALPER_BONUS_PCT = 0.05                # +5% allocation for titulars with 3+ consecutive wins
SCALPER_MAX_OPEN_POSITIONS = 16         # global sanity cap (capital is the real limit)

# v3.0: Never copy these market types even if a titular's profile shows edge on
# them. Micro-timeframe (5-15 min) binary markets are near-random for a copy
# bot because the system's latency + titular's decision latency already consumed
# any edge. "unclassified" and "other" are catch-all buckets that let in
# unknown markets silently — default-deny is safer than default-allow.
SCALPER_BLOCKED_MARKET_TYPES = frozenset({
    "unclassified",
    "other",
    "crypto_updown_micro",
    "crypto_updown_short",
})

# v3.0: wallet health gate — skip titulars whose current portfolio_value on
# Polymarket data-api is below this threshold (essentially wiped out).
SCALPER_MIN_TITULAR_PORTFOLIO_USD = 100.0
# v3.0: skip titulars where enricher HR diverges from last-30d actual WR by
# more than this (in percentage points). Protects against stale/inflated HR.
SCALPER_MAX_HR_WR_DIVERGENCE = 0.20

# V2 rotation & cooldown
SCALPER_HEALTH_CHECK_HOURS = 72         # hours between health checks (no forced weekly rotation)
SCALPER_COOLDOWN_DAYS_BASE = 30         # base cooldown for removed titulars
SCALPER_PRIORITY_BOOST = 1.3            # composite score multiplier for priority market types

# V1 legacy (kept for rotation_engine compatibility during transition)
SCALPER_COPY_RATIO_MIN = 0.05
SCALPER_COPY_RATIO_MAX = 0.10
SCALPER_MAX_PER_TRADE = 100
SCALPER_SHARPE_WINDOW_DAYS = 14
SCALPER_ROTATION_DAY = "monday"
SCALPER_ROTATION_HOUR_UTC = 0

# Specialist CB: higher threshold because the strategy holds few positions
# over multi-hour horizons — 3 losses in a row is normal variance, not a
# systemic failure. Revisit after ≥30 closed positions.
SPECIALIST_CONSECUTIVE_LOSS_LIMIT = 5

# ── Specialist Edge strategy ─────────────────────────────
SPECIALIST_INITIAL_CAPITAL = float(os.getenv("SPECIALIST_INITIAL_CAPITAL", "1000"))

# Universes: name → {capital_pct, max_slots, market_types, sl_pct}
# sl_pct: stop-loss threshold from entry (None = disabled, rely on TS + exposure cap)
SPECIALIST_UNIVERSES = {
    "crypto_above_below": {
        "capital_pct": 0.40,
        "max_slots": 3,
        "market_types": ["crypto_above", "crypto_below"],
        "sl_pct": None,        # No SL: crypto noise resolves before market close
    },
    "sports_game_winner": {
        "capital_pct": 0.40,
        "max_slots": 3,
        "market_types": ["sports_winner", "sports_spread"],
        "sl_pct": -0.50,       # Tightened from -0.70 after 3 SL hits in v2.0 run lost $215
    },
    "financial_markets": {
        "capital_pct": 0.20,
        "max_slots": 2,
        "market_types": ["financial_index", "financial_commodity", "financial_stock"],
        "sl_pct": None,        # No SL: daily resolution, same logic as crypto
    },
}

# Specialist detection thresholds
SPEC_MIN_UNIVERSE_TRADES = 10       # Min resolved trades in universe
SPEC_MIN_HIT_RATE = 0.58            # Min hit rate to qualify
SPEC_MIN_SCORE = 0.35               # Min specialist_score
SPEC_MAX_INACTIVE_DAYS = 14         # Must have been active within 14 days
SPEC_MAX_RANKING_SIZE = 200         # Max specialists per universe in DB

# Signal quality thresholds (spec §8)
# v3.0: raised after v2.1 review — CLEAN @ 2.5× and 2 specialists produced
# WR 11% in 15 real trades. Specialist count <4 produced WR 0%. Matching the
# empirical distribution instead of the original optimistic thresholds.
SIGNAL_CLEAN_RATIO = 3.0            # was 2.5
SIGNAL_CONTESTED_RATIO = 2.0        # was 1.5
SIGNAL_MIN_SPECIALISTS = 4          # was 2
SIGNAL_CONFLICT_PENALTY = 0.30      # Penalty when both sides have specialists
SPECIALIST_CONTESTED_SIZE_MULT = 0.30  # CONTESTED signals sized at 30% of CLEAN
# v3.0: expected-value gate on entry. EV = avg_hit_rate - entry_price. If the
# market already prices in more probability than specialists estimate, we'd be
# overpaying for consensus information. Default 0 = reject any negative EV.
EV_MIN_ENTRY = 0.0

# Market filtering for routing
SPECIALIST_MARKET_MIN_VOLUME_24H = 50_000  # $50K min 24h volume
SPECIALIST_MARKET_MAX_HOURS = 24    # Only <=24h markets
SPECIALIST_MARKET_MIN_PRICE = 0.12  # Min token price (avoid near-certain)
SPECIALIST_MARKET_MAX_PRICE = 0.88  # Max token price
SPECIALIST_MARKET_MAX_SPREAD = 0.06 # Max bid-ask spread

# Trade sizing
SPECIALIST_TRADE_PCT = 0.25         # 25% of universe capital per trade
SPECIALIST_MAX_TRADE_USD = 200      # Safety cap per trade
SPECIALIST_MIN_TRADE_USD = 10       # Floor per trade
SPECIALIST_MAX_EXPOSURE_PCT = 0.50  # Max total open exposure as % of portfolio

# Trailing stop (spec §10)
TS_ACTIVATION = 0.08                # Activate trailing after +8% gain
TS_TRAIL_PCT = 0.15                 # Trail 15% below high-water mark
TS_HARD_STOP = -0.20                # Hard stop at -20%

# Routing
HYBRID_BD_ONLY_MIN_KNOWN = 3        # Use DB-only when >=3 known specialists
HYBRID_BD_ONLY_MIN_HR = 0.60        # All known must have HR >= 60%
HYBRID_BD_ONLY_MAX_AGE_HOURS = 12   # Data fresh (< 12h)
ANTI_BLINDNESS_FORCE_SCAN_EVERY = 10  # Force FULL_SCAN every N BD-only decisions
SPEC_MAX_UNKNOWNS_PER_MARKET = 10   # Max unknown holders to profile per market (caps tick time)

# Type rankings (spec §6)
TYPE_MIN_SPECIALISTS_TO_RANK = 3    # Need >=3 specialists before ranking type
TYPE_RECOMPUTE_INTERVAL_HOURS = 6   # Recompute type rankings every 6h

# ── Quarantine ───────────────────────────────────────────
QUARANTINE_BOT_DAYS = 30
QUARANTINE_LOSS_DAYS = 14
QUARANTINE_REENTRY_STRICT = True

# ── Category tag keyword maps (used by gamma_client) ─────
CATEGORY_KEYWORDS = {
    "crypto": [
        "crypto", "bitcoin", "btc", "eth", "ethereum", "solana", "sol",
        "memecoin", "defi", "token", "blockchain",
    ],
    "politics": [
        "politic", "election", "president", "congress", "senate", "trump",
        "democrat", "republican", "governor", "vote", "geopolit", "war",
        "nato", "tariff",
    ],
    "economics": [
        "econom", "fed", "rate", "inflation", "gdp", "recession",
        "interest rate", "cpi", "jobs", "unemployment", "treasury",
        "bond", "fiscal",
    ],
}
