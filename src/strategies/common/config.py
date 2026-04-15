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
BASKET_MAX_WALLETS = 10
BASKET_CONSENSUS_THRESHOLD = 0.80
BASKET_TIME_WINDOW_HOURS = 4
BASKET_MAX_CAPITAL_PCT = 0.30
BASKET_EXIT_CONSENSUS = 0.50
BASKET_MONITOR_INTERVAL_SECONDS = 60

# ── Scalper strategy ─────────────────────────────────────
SCALPER_ACTIVE_WALLETS = 3
SCALPER_POOL_SIZE = 12
SCALPER_COPY_RATIO_MIN = 0.05
SCALPER_COPY_RATIO_MAX = 0.10
SCALPER_MAX_PER_TRADE = 100
SCALPER_MIN_PER_TRADE = 5
SCALPER_SHARPE_WINDOW_DAYS = 14
SCALPER_ROTATION_DAY = "monday"
SCALPER_ROTATION_HOUR_UTC = 0
SCALPER_CONSECUTIVE_LOSS_LIMIT = 3
SCALPER_MONITOR_INTERVAL_SECONDS = 30

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
