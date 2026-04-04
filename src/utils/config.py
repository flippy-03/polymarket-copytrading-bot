import os
from dotenv import load_dotenv

load_dotenv()

# === SUPABASE ===
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# === POLYMARKETSCAN ===
POLYMARKETSCAN_API_URL = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api"
POLYMARKETSCAN_API_KEY = os.environ["POLYMARKETSCAN_API_KEY"]
POLYMARKETSCAN_AGENT_API_URL = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api"

# === FALCON / NARRATIVE API ===
# Parameterized endpoint currently returns 400 (server-side pipeline error).
# Implemented for future use — gracefully returns empty on failure.
FALCON_API_URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
FALCON_BEARER_TOKEN = os.environ.get("FALCON_BEARER_TOKEN", "")

# === ESTRATEGIA ===
DIVERGENCE_THRESHOLD_MIN = 0.10
DIVERGENCE_THRESHOLD_STRONG = 0.15

# Filtros de mercado
MIN_VOLUME_24H = 10_000
MIN_LIQUIDITY = 5_000
MIN_HOURS_TO_RESOLUTION = 6
MAX_HOURS_TO_RESOLUTION = 168
EXCLUDED_CATEGORIES = ["sports"]

# Palabras clave en el titulo del mercado que indican deportes.
# Necesario porque la Gamma API devuelve category='' para la mayoria de mercados,
# por lo que el filtro por categoria sola no funciona.
SPORTS_QUESTION_KEYWORDS = [
    " vs. ",   # matchups deportivos (Jets vs. Rangers, etc.)
    " o/u ",   # over/under
    "o/u ",    # over/under al inicio
    " win on 20",  # "Will X win on 2026-..."
    " cf win",     # club de futbol
    " fc win",     # football club
    " sc win",     # sports club
]

# Crypto price-target markets ("Will BTC reach $70k?", "Will ETH dip to $1,900?").
# Shadow trade analysis: 0% WR -$64 P&L vs 66.7% WR +$34 for event markets.
# Correlated intra-day (all move together on macro events) → capped at MAX_CRYPTO_POSITIONS.
PRICE_TARGET_KEYWORDS = [
    "reach $",
    "dip to $",
    "hit $",
    "fall to $",
    "drop to $",
    "above $",
    "below $",
    "be between $",
    "price of bitcoin",
    "price of ethereum",
    "price of eth",
    "price of btc",
]

# Max simultaneous open positions in crypto price-target markets.
# Limits correlated drawdown on macro shock days (e.g. March 31: 5 simultaneous → -$79).
MAX_CRYPTO_POSITIONS = 3

# Cooldown after a market closes via TRAILING_STOP or TAKE_PROFIT.
# Prevents re-entering the same market within this window (e.g. ETH $2100 traded twice in 35min).
MARKET_REENTRY_COOLDOWN_HOURS = 24

# Precio minimo de entrada para evitar mercados sub-centavo con volatilidad absurda.
# Un precio de 0.009 significa spread relativo del 10%+, destruye el edge.
MIN_ENTRY_PRICE = 0.05

# Precio minimo para señales contrarian: evita entrar en mercados ya 80%+ resueltos
# en la direccion opuesta. A yes_price < 0.20, las ballenas no manipulan — hacen
# price discovery racional sobre un resultado casi cierto. Aplica simetricamente:
#   YES signal: yes_price >= MIN_CONTRARIAN_PRICE
#   NO signal:  (1 - yes_price) >= MIN_CONTRARIAN_PRICE  →  yes_price <= 0.80
MIN_CONTRARIAN_PRICE = 0.20

# === PAPER TRADING ===
INITIAL_CAPITAL = 1000.0
MAX_POSITION_SIZE_PCT = 0.05
MAX_OPEN_POSITIONS = 5
KELLY_FRACTION = 0.5

# === RISK MANAGEMENT ===
CIRCUIT_BREAKER_LOSSES = 3
CIRCUIT_BREAKER_COOLDOWN_HOURS = 12
TRAILING_STOP_PCT = 0.25
TAKE_PROFIT_PCT = 0.50
MAX_DRAWDOWN_PCT = 0.20
MAX_SIGNAL_DRIFT_PCT = 0.40  # Max relative price drift from signal before hypothesis is invalid

# === TIMING ===
SNAPSHOT_INTERVAL_SECONDS = 120
SIGNAL_CHECK_INTERVAL_SECONDS = 300
POSITION_CHECK_INTERVAL_SECONDS = 60

# === SIGNAL WEIGHTS ===
# Smart wallet score is currently static (not per-market), so its weight is
# reduced from 0.20 to 0.10. The freed weight goes to divergence (the core signal).
WEIGHT_DIVERGENCE = 0.55
WEIGHT_MOMENTUM = 0.35
WEIGHT_SMART_WALLET = 0.10
SIGNAL_THRESHOLD = 65

# === LLM FILTER ===
# Semantic validation of trades via Claude before execution.
# Fail-open: any API failure allows the trade through.
# Runtime toggle: dashboard writes llm_enabled to portfolio_state.metadata.
# The env var is the default; the DB value (if present) overrides it.
LLM_ENABLED_DEFAULT = os.environ.get("LLM_ENABLED", "false").lower() == "true"
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")

# Keep the old name for backward compat — modules that import LLM_ENABLED
# at the top level get the env default. Runtime check uses get_llm_enabled().
LLM_ENABLED = LLM_ENABLED_DEFAULT


def get_llm_enabled() -> bool:
    """Check LLM toggle from DB (portfolio_state.metadata), falling back to env var."""
    try:
        from src.db import supabase_client as _db
        client = _db.get_client()
        result = client.table("portfolio_state").select("metadata").order("run_id", desc=True).limit(1).execute()
        if result.data and result.data[0].get("metadata"):
            val = result.data[0]["metadata"].get("llm_enabled")
            if val is not None:
                return bool(val)
    except Exception:
        pass
    return LLM_ENABLED_DEFAULT
