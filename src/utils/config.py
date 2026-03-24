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

# Precio minimo de entrada para evitar mercados sub-centavo con volatilidad absurda.
# Un precio de 0.009 significa spread relativo del 10%+, destruye el edge.
MIN_ENTRY_PRICE = 0.05

# === PAPER TRADING ===
INITIAL_CAPITAL = 1000.0
MAX_POSITION_SIZE_PCT = 0.05
MAX_OPEN_POSITIONS = 5
KELLY_FRACTION = 0.5

# === RISK MANAGEMENT ===
CIRCUIT_BREAKER_LOSSES = 3
CIRCUIT_BREAKER_COOLDOWN_HOURS = 24
TRAILING_STOP_PCT = 0.25
TAKE_PROFIT_PCT = 0.50
MAX_DRAWDOWN_PCT = 0.20

# === TIMING ===
SNAPSHOT_INTERVAL_SECONDS = 120
SIGNAL_CHECK_INTERVAL_SECONDS = 300
POSITION_CHECK_INTERVAL_SECONDS = 60

# === SIGNAL WEIGHTS ===
WEIGHT_DIVERGENCE = 0.50
WEIGHT_MOMENTUM = 0.30
WEIGHT_SMART_WALLET = 0.20
SIGNAL_THRESHOLD = 65
