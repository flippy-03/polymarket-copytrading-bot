# Polymarket Copytrading — Guía de Implementación para Claude Code

> Documento de especificación técnica para construir el sistema de selección de wallets y ejecución de ambas estrategias. Separado en módulos comunes y específicos.

---

## ARQUITECTURA GENERAL

```
polymarket-copytrade/
├── common/                          # MÓDULOS COMPARTIDOS (ambas estrategias)
│   ├── __init__.py
│   ├── config.py                    # Constantes, umbrales, API URLs
│   ├── gamma_client.py              # Cliente Gamma API (descubrimiento de mercados)
│   ├── data_client.py               # Cliente Data API (trades, posiciones, actividad)
│   ├── clob_client.py               # Cliente CLOB API (order book, ejecución)
│   ├── wallet_analyzer.py           # Análisis de métricas de wallets
│   ├── wallet_filter.py             # Pipeline de filtros Tier 1/2/3
│   ├── bot_detector.py              # Tests de detección bot vs humano
│   ├── risk_manager.py              # Circuit breakers, sizing, drawdown
│   └── db.py                        # Capa de persistencia (SQLite o Supabase)
│
├── strategy_basket/                 # ESTRATEGIA 1: Wallet Basket Consensus
│   ├── __init__.py
│   ├── basket_builder.py            # Construcción de baskets temáticos
│   ├── consensus_engine.py          # Motor de evaluación de consenso
│   ├── basket_monitor.py            # Monitoreo continuo de wallets en baskets
│   └── basket_executor.py           # Ejecución de señales de consenso
│
├── strategy_scalper/                # ESTRATEGIA 2: Scalper Rotator
│   ├── __init__.py
│   ├── pool_builder.py              # Construcción del pool de candidatos
│   ├── rotation_engine.py           # Selección semanal por Sharpe
│   ├── copy_monitor.py              # Copia directa en tiempo real
│   └── scalper_executor.py          # Ejecución de copias
│
├── main.py                          # Entry point
├── requirements.txt
└── .env
```

---

## PARTE 1 — MÓDULOS COMUNES (ambas estrategias usan estos)

### 1.1 config.py — Constantes y configuración

```python
"""
config.py — Configuración central del sistema de copytrading.
Todas las constantes, umbrales y URLs viven aquí.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# ─── API URLs ─────────────────────────────────────────────
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API  = "https://data-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"
CLOB_WSS  = "wss://ws-subscriptions-clob.polymarket.com"

# ─── Auth ─────────────────────────────────────────────────
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")
POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")

# ─── Filtros Tier 1 (eliminatorios) ──────────────────────
MIN_WIN_RATE = 0.60             # 60% mínimo con 100+ trades
MIN_TRADES_TOTAL = 100          # Para que win rate sea significativo
MIN_TRACK_RECORD_DAYS = 120     # 4 meses mínimo
MAX_HOLDING_PERIOD_DAYS = 7     # Holding period medio máximo
MIN_TRADES_PER_MONTH = 8        # Frecuencia mínima
REQUIRE_POSITIVE_PNL_30D = True
REQUIRE_NONNEGATIVE_PNL_7D = True

# ─── Filtros Tier 2 (calidad del edge) ───────────────────
MIN_PROFIT_FACTOR = 1.5         # Ganancias brutas / pérdidas brutas
MIN_EDGE_VS_ODDS = 0.05         # +5% win rate vs implied probability
MIN_MARKET_CATEGORIES = 3       # Diversificación mínima
MIN_POSITIVE_WEEKS_PCT = 0.65   # 65% semanas positivas
POSITION_SIZE_RANGE = (100, 10_000)  # Avg position size aceptable
TIER2_MIN_PASS = 4              # Mínimo 4 de 6 filtros Tier 2

# ─── Detección de bots ───────────────────────────────────
BOT_MIN_TESTS_PASS = 4          # De 5 tests, pasar al menos 4
# Test 1: Coeficiente de variación de intervalos entre trades
BOT_INTERVAL_CV_MIN = 0.30      # CV > 0.30 = probable humano
# Test 2: Coeficiente de variación de position sizes
BOT_SIZE_CV_MIN = 0.30
# Test 3: Correlación de delay con otro wallet
BOT_MAX_CORRELATION_SCORE = 0.70
# Test 4: Originalidad de mercados (% mercados únicos vs whale pool)
BOT_MIN_UNIQUE_MARKETS_PCT = 0.15
# Test 5: Frecuencia máxima (trades/mes) para no ser market maker
BOT_MAX_TRADES_PER_MONTH = 500

# ─── Risk Management ─────────────────────────────────────
MAX_DRAWDOWN_PCT = 0.30
DAILY_LOSS_LIMIT = 0.10
MAX_OPEN_POSITIONS = 8
MAX_PER_MARKET_PCT = 0.15
MAX_PER_TRADE_PCT = 0.10
TIMEOUT_DAYS = 7
MIN_LIQUIDITY_24H = 100_000     # $100K volumen mínimo
MAX_SLIPPAGE = 0.05
MAX_ENTRY_DRIFT = 0.10

# ─── Basket Strategy ─────────────────────────────────────
BASKET_MIN_WALLETS = 5
BASKET_MAX_WALLETS = 10
BASKET_CONSENSUS_THRESHOLD = 0.80   # 80% deben coincidir
BASKET_TIME_WINDOW_HOURS = 4
BASKET_MAX_CAPITAL_PCT = 0.30       # Max 30% capital en un basket
BASKET_EXIT_CONSENSUS = 0.50        # 50% cierran = cerrar

# ─── Scalper Strategy ────────────────────────────────────
SCALPER_ACTIVE_WALLETS = 3          # 2-3 titulares activos
SCALPER_POOL_SIZE = 12              # 8-12 en bench
SCALPER_COPY_RATIO_MIN = 0.05
SCALPER_COPY_RATIO_MAX = 0.10
SCALPER_MAX_PER_TRADE = 100         # $100 max
SCALPER_SHARPE_WINDOW_DAYS = 14
SCALPER_ROTATION_DAY = "monday"
SCALPER_ROTATION_HOUR_UTC = 0
SCALPER_CONSECUTIVE_LOSS_LIMIT = 3  # 3 pérdidas >10% = cuarentena

# ─── Cuarentena ───────────────────────────────────────────
QUARANTINE_BOT_DAYS = 30
QUARANTINE_LOSS_DAYS = 14
QUARANTINE_REENTRY_STRICT = True    # Tier 1 + Tier 2 completos

# ─── Tags de categoría conocidos en Gamma API ────────────
# Estos son los tag_ids que usaremos para los 3 baskets iniciales.
# Obtener la lista completa con GET /tags.
# Se actualizan dinámicamente al arrancar el sistema.
CATEGORY_TAGS = {
    "crypto": [],       # Se llena en runtime con tags de crypto
    "politics": [],     # Se llena en runtime con tags de política
    "economics": [],    # Se llena en runtime con tags de economía/fed
}
```

### 1.2 gamma_client.py — Descubrimiento de mercados

```python
"""
gamma_client.py — Cliente para la Gamma API de Polymarket.
Descubrimiento de mercados, tags, categorías. Sin autenticación.

Endpoints principales:
  GET /tags                   → Lista de todas las categorías
  GET /events?tag_id=X        → Eventos filtrados por categoría
  GET /markets?active=true    → Mercados activos
  GET /events?active=true&closed=false&order=volume_24hr → Top por volumen
"""
import requests
import time
from typing import Optional
from common.config import GAMMA_API, MIN_LIQUIDITY_24H

class GammaClient:
    """
    Cliente read-only para la Gamma API.
    Rate limit: ~4000 req / 10s general, 500/10s para /events, 300/10s para /markets.
    """

    def __init__(self):
        self.base = GAMMA_API
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict = None) -> list | dict:
        """GET request con retry y backoff."""
        url = f"{self.base}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=15)
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    raise
                time.sleep(1)

    # ─── Tags / Categorías ────────────────────────────────

    def get_all_tags(self) -> list[dict]:
        """
        GET /tags → lista de todos los tags disponibles.
        Cada tag tiene: id, label, slug.
        Usar para mapear categorías temáticas a tag_ids.
        """
        return self._get("/tags")

    def discover_category_tags(self) -> dict[str, list[int]]:
        """
        Descubre automáticamente los tag_ids para las categorías principales.
        Busca tags cuyo label/slug contenga keywords de cada categoría.

        Returns:
            {
                "crypto": [tag_id, tag_id, ...],
                "politics": [tag_id, ...],
                "economics": [tag_id, ...],
            }
        """
        all_tags = self.get_all_tags()
        category_keywords = {
            "crypto": ["crypto", "bitcoin", "btc", "eth", "ethereum", "solana",
                        "sol", "memecoin", "defi", "token", "blockchain"],
            "politics": ["politic", "election", "president", "congress", "senate",
                          "trump", "democrat", "republican", "governor", "vote",
                          "geopolit", "war", "nato", "tariff"],
            "economics": ["econom", "fed", "rate", "inflation", "gdp", "recession",
                           "interest rate", "cpi", "jobs", "unemployment",
                           "treasury", "bond", "fiscal"],
        }
        result = {cat: [] for cat in category_keywords}
        for tag in all_tags:
            label = (tag.get("label", "") or "").lower()
            slug = (tag.get("slug", "") or "").lower()
            combined = f"{label} {slug}"
            for cat, keywords in category_keywords.items():
                if any(kw in combined for kw in keywords):
                    tag_id = tag.get("id")
                    if tag_id and tag_id not in result[cat]:
                        result[cat].append(tag_id)
        return result

    # ─── Mercados ─────────────────────────────────────────

    def get_active_markets(
        self,
        tag_id: Optional[int] = None,
        min_volume_24h: float = MIN_LIQUIDITY_24H,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Obtiene mercados activos, opcionalmente filtrados por tag.
        Ordenados por volumen 24h descendente.

        Cada mercado devuelve:
          - id, question, slug, conditionId
          - outcomes (["Yes","No"]), outcomePrices
          - volume24hr, volume, liquidity
          - clobTokenIds (los token IDs para CLOB API)
          - endDate (fecha de resolución)
          - tags (array de tag objects)
        """
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume_24hr",
            "ascending": "false",
            "limit": limit,
            "offset": offset,
        }
        if tag_id:
            params["tag_id"] = tag_id

        markets = self._get("/markets", params)
        # Filtrar por volumen mínimo
        return [m for m in markets if (m.get("volume24hr") or 0) >= min_volume_24h]

    def get_events_by_tag(
        self,
        tag_id: int,
        limit: int = 50,
        active_only: bool = True,
    ) -> list[dict]:
        """
        Obtiene eventos filtrados por tag.
        Cada evento contiene un array 'markets' con los mercados hijos.
        """
        params = {
            "tag_id": tag_id,
            "limit": limit,
            "order": "volume_24hr",
            "ascending": "false",
        }
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        return self._get("/events", params)

    def get_markets_resolving_within(self, days: int = 7) -> list[dict]:
        """
        Obtiene mercados cuya fecha de resolución (endDate) es dentro de N días.
        CRÍTICO para tu restricción de máximo 7 días de holding.

        Nota: La Gamma API no tiene un filtro directo por endDate range,
        así que obtenemos todos los activos y filtramos localmente.
        Para eficiencia, paginar con limit/offset.
        """
        import datetime
        cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        cutoff_iso = cutoff.isoformat() + "Z"

        all_markets = []
        offset = 0
        while True:
            batch = self.get_active_markets(limit=100, offset=offset, min_volume_24h=0)
            if not batch:
                break
            all_markets.extend(batch)
            offset += 100
            if len(batch) < 100:
                break

        # Filtrar los que resuelven dentro del plazo
        result = []
        for m in all_markets:
            end_date = m.get("endDate") or m.get("end_date_iso")
            if end_date and end_date <= cutoff_iso:
                result.append(m)

        return sorted(result, key=lambda m: m.get("volume24hr", 0), reverse=True)

    def get_market_by_slug(self, slug: str) -> dict:
        """Obtiene un mercado específico por su slug."""
        return self._get(f"/markets/slug/{slug}")

    def get_market_by_id(self, market_id: int) -> dict:
        """Obtiene un mercado por su ID numérico."""
        return self._get(f"/markets/{market_id}")
```

### 1.3 data_client.py — Trades, posiciones, actividad de wallets

```python
"""
data_client.py — Cliente para la Data API de Polymarket.
Obtiene trades, posiciones, actividad de wallets. Sin autenticación necesaria.

Base URL: https://data-api.polymarket.com

Endpoints principales:
  GET /activity?user=0x...     → Actividad on-chain (trades, splits, merges)
  GET /positions?user=0x...    → Posiciones abiertas
  GET /trades?market=0x...     → Trades por mercado
  GET /holders?conditionId=0x... → Top holders de un mercado
"""
import requests
import time
from typing import Optional
from common.config import DATA_API

class DataClient:
    """
    Cliente para Data API. Rate limit: ~30 req/s.
    Paginación: limit (max 500) + offset.
    """

    def __init__(self):
        self.base = DATA_API
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict = None) -> list | dict:
        url = f"{self.base}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=15)
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException:
                if attempt == 2:
                    raise
                time.sleep(1)

    # ─── Actividad de un wallet ───────────────────────────

    def get_wallet_activity(
        self,
        wallet: str,
        type_filter: str = "TRADE",
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """
        Obtiene la actividad de un wallet.

        Args:
            wallet: Dirección proxy del wallet (0x...)
            type_filter: TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION
            start: Timestamp UNIX (segundos) inicio
            end: Timestamp UNIX (segundos) fin

        Returns:
            Lista de actividades. Cada TRADE contiene:
            - proxyWallet, timestamp, conditionId, type
            - size (tokens), usdcSize, price, side (BUY/SELL)
            - outcome (Yes/No), title, slug, eventSlug
        """
        params = {
            "user": wallet,
            "type": type_filter,
            "limit": limit,
            "offset": offset,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get("/activity", params)

    def get_all_wallet_trades(
        self,
        wallet: str,
        start: Optional[int] = None,
        max_pages: int = 20,
    ) -> list[dict]:
        """
        Obtiene TODOS los trades de un wallet paginando automáticamente.
        La Data API devuelve max 500 por request.

        Args:
            wallet: Dirección proxy
            start: Timestamp opcional para limitar al periodo reciente
            max_pages: Límite de páginas para evitar bucles infinitos

        Returns:
            Lista completa de trades ordenados por timestamp DESC.
        """
        all_trades = []
        offset = 0
        for _ in range(max_pages):
            batch = self.get_wallet_activity(
                wallet, type_filter="TRADE", start=start, limit=500, offset=offset
            )
            if not batch:
                break
            all_trades.extend(batch)
            if len(batch) < 500:
                break
            offset += 500
            time.sleep(0.1)  # Respetar rate limit
        return all_trades

    # ─── Posiciones ───────────────────────────────────────

    def get_wallet_positions(
        self,
        wallet: str,
        sort_by: str = "CURRENT",
        limit: int = 100,
    ) -> list[dict]:
        """
        Obtiene posiciones abiertas de un wallet.

        Returns:
            Cada posición contiene:
            - asset, conditionId, size, avgPrice
            - initialValue, currentValue, cashPnl, percentPnl
            - realizedPnl, curPrice, title, slug
        """
        params = {
            "user": wallet,
            "sortBy": sort_by,
            "sortDirection": "DESC",
            "limit": limit,
        }
        return self._get("/positions", params)

    # ─── Holders de un mercado ────────────────────────────

    def get_market_holders(
        self,
        condition_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """
        Obtiene los top holders de un mercado específico.
        Esto es CLAVE para el basket builder: identificar qué wallets
        tienen posiciones grandes en mercados de una categoría.

        Args:
            condition_id: El conditionId del mercado (0x...)
        """
        params = {"conditionId": condition_id, "limit": limit}
        return self._get("/holders", params)

    # ─── Trades de un mercado ─────────────────────────────

    def get_market_trades(
        self,
        condition_id: str,
        limit: int = 500,
    ) -> list[dict]:
        """
        Obtiene los trades recientes de un mercado.
        Útil para identificar wallets activos en un mercado concreto.
        """
        params = {"market": condition_id, "limit": limit}
        return self._get("/trades", params)
```

### 1.4 wallet_analyzer.py — Cálculo de métricas de un wallet

```python
"""
wallet_analyzer.py — Calcula todas las métricas necesarias para evaluar un wallet.
Recibe trades crudos de data_client y devuelve un WalletMetrics dataclass.

MÓDULO COMPARTIDO: Ambas estrategias usan este analyzer.
"""
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class WalletMetrics:
    """Métricas calculadas para un wallet."""
    address: str

    # Tier 1
    total_trades: int = 0
    win_rate: float = 0.0
    track_record_days: int = 0
    avg_holding_period_hours: float = 0.0
    pnl_30d: float = 0.0
    pnl_7d: float = 0.0
    trades_per_month: float = 0.0

    # Tier 2
    profit_factor: float = 0.0
    edge_vs_odds: float = 0.0         # win_rate - avg_entry_price
    unique_categories: int = 0
    positive_weeks_pct: float = 0.0
    avg_position_size: float = 0.0
    entry_timing_score: float = 0.0   # Experimental

    # Bot detection
    interval_cv: float = 0.0          # Coeficiente variación entre trades
    size_cv: float = 0.0              # Coeficiente variación de sizes
    max_corr_delay: float = 0.0       # Correlación temporal con otro wallet
    unique_markets_pct: float = 0.0   # % mercados no operados por top whales
    is_likely_bot: bool = False

    # Metadata
    categories: list[str] = field(default_factory=list)
    first_trade_ts: int = 0
    last_trade_ts: int = 0
    total_pnl: float = 0.0


def analyze_wallet(trades: list[dict], address: str) -> WalletMetrics:
    """
    Calcula todas las métricas a partir del histórico de trades crudo.

    Args:
        trades: Lista de trades del Data API (output de get_all_wallet_trades).
                Cada trade tiene: timestamp, price, side, usdcSize, size,
                conditionId, outcome, title, slug, eventSlug
        address: La dirección proxy del wallet.

    Returns:
        WalletMetrics con todas las métricas calculadas.
    """
    m = WalletMetrics(address=address)
    if not trades:
        return m

    # ─── Datos básicos ────────────────────────────────────
    m.total_trades = len(trades)
    timestamps = sorted([t["timestamp"] for t in trades])
    m.first_trade_ts = timestamps[0]
    m.last_trade_ts = timestamps[-1]
    m.track_record_days = (m.last_trade_ts - m.first_trade_ts) // 86400

    # Trades por mes
    if m.track_record_days > 0:
        m.trades_per_month = m.total_trades / (m.track_record_days / 30)

    # ─── Categorías (diversificación) ─────────────────────
    event_slugs = set()
    market_slugs = set()
    for t in trades:
        es = t.get("eventSlug", "")
        ms = t.get("slug", "")
        if es:
            event_slugs.add(es)
        if ms:
            market_slugs.add(ms)

    # Heurística de categorías basada en keywords del slug/título
    category_keywords = {
        "crypto": ["btc", "bitcoin", "eth", "ethereum", "sol", "solana",
                    "crypto", "token", "defi", "memecoin"],
        "politics": ["election", "president", "trump", "biden", "vote",
                      "congress", "senate", "governor", "political"],
        "economics": ["fed", "rate", "inflation", "gdp", "recession",
                       "cpi", "unemployment", "treasury"],
        "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football",
                    "game", "match", "championship"],
        "tech": ["ai", "openai", "google", "apple", "microsoft", "tech",
                  "spacex", "tesla"],
    }
    found_cats = set()
    for t in trades:
        title = (t.get("title", "") or "").lower()
        slug = (t.get("slug", "") or "").lower()
        combined = f"{title} {slug}"
        for cat, kws in category_keywords.items():
            if any(kw in combined for kw in kws):
                found_cats.add(cat)
    m.categories = list(found_cats)
    m.unique_categories = len(found_cats)

    # ─── Win rate y PnL ───────────────────────────────────
    # Agrupar trades por mercado (conditionId) para calcular P&L por mercado
    from collections import defaultdict
    market_trades = defaultdict(list)
    for t in trades:
        cid = t.get("conditionId", "unknown")
        market_trades[cid].append(t)

    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    total_entry_prices = []
    holding_periods = []

    now_ts = int(datetime.utcnow().timestamp())
    ts_30d_ago = now_ts - 30 * 86400
    ts_7d_ago = now_ts - 7 * 86400
    pnl_30d = 0.0
    pnl_7d = 0.0

    for cid, mkt_trades in market_trades.items():
        # Calcular PnL neto de este mercado
        buys = [t for t in mkt_trades if t.get("side") == "BUY"]
        sells = [t for t in mkt_trades if t.get("side") == "SELL"]

        total_buy_cost = sum(t.get("usdcSize", 0) for t in buys)
        total_sell_revenue = sum(t.get("usdcSize", 0) for t in sells)
        net_pnl = total_sell_revenue - total_buy_cost

        # Para mercados resueltos, las redemptions aparecen como REDEEM,
        # pero en trades solo vemos BUY/SELL. Aproximación: si hay más
        # sells que buys, el trader cerró con ganancia.
        if net_pnl > 0:
            wins += 1
            gross_profit += net_pnl
        elif net_pnl < 0:
            losses += 1
            gross_loss += abs(net_pnl)

        # PnL por ventana temporal
        recent_trades = [t for t in mkt_trades if t["timestamp"] >= ts_30d_ago]
        if recent_trades:
            rb = sum(t.get("usdcSize", 0) for t in recent_trades if t.get("side") == "BUY")
            rs = sum(t.get("usdcSize", 0) for t in recent_trades if t.get("side") == "SELL")
            pnl_30d += (rs - rb)

        recent_7d = [t for t in mkt_trades if t["timestamp"] >= ts_7d_ago]
        if recent_7d:
            rb7 = sum(t.get("usdcSize", 0) for t in recent_7d if t.get("side") == "BUY")
            rs7 = sum(t.get("usdcSize", 0) for t in recent_7d if t.get("side") == "SELL")
            pnl_7d += (rs7 - rb7)

        # Holding period: diferencia entre primer BUY y último SELL
        if buys and sells:
            first_buy_ts = min(t["timestamp"] for t in buys)
            last_sell_ts = max(t["timestamp"] for t in sells)
            hp_hours = (last_sell_ts - first_buy_ts) / 3600
            if hp_hours > 0:
                holding_periods.append(hp_hours)

        # Entry prices para edge calculation
        for t in buys:
            total_entry_prices.append(t.get("price", 0.5))

    total_markets = wins + losses
    m.win_rate = wins / total_markets if total_markets > 0 else 0
    m.pnl_30d = pnl_30d
    m.pnl_7d = pnl_7d
    m.total_pnl = gross_profit - gross_loss
    m.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    m.avg_holding_period_hours = np.mean(holding_periods) if holding_periods else 0

    # Edge vs odds: win_rate - average entry price
    # Entry price IS the implied probability on Polymarket
    if total_entry_prices:
        avg_entry = np.mean(total_entry_prices)
        m.edge_vs_odds = m.win_rate - avg_entry

    # ─── Position sizing ──────────────────────────────────
    sizes = [t.get("usdcSize", 0) for t in trades if t.get("side") == "BUY"]
    if sizes:
        m.avg_position_size = np.mean(sizes)
        m.size_cv = np.std(sizes) / np.mean(sizes) if np.mean(sizes) > 0 else 0

    # ─── Consistencia semanal ─────────────────────────────
    from collections import Counter
    weekly_pnl = Counter()
    for t in trades:
        week = datetime.utcfromtimestamp(t["timestamp"]).isocalendar()[:2]
        usdc = t.get("usdcSize", 0)
        if t.get("side") == "SELL":
            weekly_pnl[week] += usdc
        else:
            weekly_pnl[week] -= usdc
    if weekly_pnl:
        positive_weeks = sum(1 for v in weekly_pnl.values() if v > 0)
        m.positive_weeks_pct = positive_weeks / len(weekly_pnl)

    # ─── Intervalos entre trades (para bot detection) ─────
    if len(timestamps) > 1:
        intervals = np.diff(timestamps).astype(float)
        if np.mean(intervals) > 0:
            m.interval_cv = np.std(intervals) / np.mean(intervals)

    return m
```

### 1.5 wallet_filter.py — Pipeline de filtros

```python
"""
wallet_filter.py — Pipeline de filtros secuenciales.
Aplica Tier 1 → Tier 2 → Tier 3 (alertas) → Bot detection.

MÓDULO COMPARTIDO: Ambas estrategias usan este pipeline.
"""
from common.wallet_analyzer import WalletMetrics
from common import config as C


def passes_tier1(m: WalletMetrics) -> tuple[bool, str]:
    """
    Filtros eliminatorios. Si falla uno, retorna (False, motivo).
    """
    if m.total_trades < C.MIN_TRADES_TOTAL:
        return False, f"trades={m.total_trades} < {C.MIN_TRADES_TOTAL}"
    if m.win_rate < C.MIN_WIN_RATE:
        return False, f"win_rate={m.win_rate:.2%} < {C.MIN_WIN_RATE:.0%}"
    if m.track_record_days < C.MIN_TRACK_RECORD_DAYS:
        return False, f"track_record={m.track_record_days}d < {C.MIN_TRACK_RECORD_DAYS}d"
    if m.avg_holding_period_hours > C.MAX_HOLDING_PERIOD_DAYS * 24:
        return False, f"holding={m.avg_holding_period_hours:.0f}h > {C.MAX_HOLDING_PERIOD_DAYS*24}h"
    if C.REQUIRE_POSITIVE_PNL_30D and m.pnl_30d <= 0:
        return False, f"pnl_30d=${m.pnl_30d:.2f} <= 0"
    if C.REQUIRE_NONNEGATIVE_PNL_7D and m.pnl_7d < 0:
        return False, f"pnl_7d=${m.pnl_7d:.2f} < 0"
    if m.trades_per_month < C.MIN_TRADES_PER_MONTH:
        return False, f"freq={m.trades_per_month:.1f}/mo < {C.MIN_TRADES_PER_MONTH}"
    return True, "OK"


def count_tier2_passes(m: WalletMetrics) -> tuple[int, list[str]]:
    """
    Filtros de calidad. Retorna (num_passed, list_of_results).
    Necesita pasar >= TIER2_MIN_PASS de 6.
    """
    results = []
    passed = 0

    # 1. Profit factor
    ok = m.profit_factor >= C.MIN_PROFIT_FACTOR
    results.append(f"profit_factor={m.profit_factor:.2f} {'✓' if ok else '✗'}")
    passed += int(ok)

    # 2. Edge vs odds
    ok = m.edge_vs_odds >= C.MIN_EDGE_VS_ODDS
    results.append(f"edge_vs_odds={m.edge_vs_odds:.2%} {'✓' if ok else '✗'}")
    passed += int(ok)

    # 3. Diversificación
    ok = m.unique_categories >= C.MIN_MARKET_CATEGORIES
    results.append(f"categories={m.unique_categories} {'✓' if ok else '✗'}")
    passed += int(ok)

    # 4. Consistencia semanal
    ok = m.positive_weeks_pct >= C.MIN_POSITIVE_WEEKS_PCT
    results.append(f"pos_weeks={m.positive_weeks_pct:.0%} {'✓' if ok else '✗'}")
    passed += int(ok)

    # 5. Avg position size
    low, high = C.POSITION_SIZE_RANGE
    ok = low <= m.avg_position_size <= high
    results.append(f"avg_size=${m.avg_position_size:.0f} {'✓' if ok else '✗'}")
    passed += int(ok)

    # 6. Entry timing (placeholder — difícil de calcular sin price history)
    # Por ahora, pasa si edge_vs_odds > 0 (proxy razonable)
    ok = m.edge_vs_odds > 0
    results.append(f"entry_timing={'pre-move' if ok else 'post-move'} {'✓' if ok else '✗'}")
    passed += int(ok)

    return passed, results


def check_tier3_alerts(m: WalletMetrics) -> list[str]:
    """
    Tier 3: Señales de alerta → descarte inmediato si aparece alguna.
    """
    alerts = []
    if m.win_rate >= 1.0 and m.total_trades < 20:
        alerts.append("100% win rate con <20 trades (suerte/insider)")
    if m.track_record_days < 30 and m.total_pnl > 5000:
        alerts.append("Wallet <1 mes con PnL alto (insider de uso único)")
    if m.trades_per_month > C.BOT_MAX_TRADES_PER_MONTH:
        alerts.append(f"Frecuencia extrema: {m.trades_per_month:.0f}/mes (market maker)")
    return alerts


def full_filter_pipeline(m: WalletMetrics) -> tuple[bool, dict]:
    """
    Ejecuta el pipeline completo: Tier1 → Tier3 → Tier2 → Bot.

    Returns:
        (passes: bool, report: dict)
    """
    report = {"address": m.address, "tier1": None, "tier2": None,
              "tier3": None, "bot": None, "final": False}

    # Tier 1
    t1_ok, t1_reason = passes_tier1(m)
    report["tier1"] = {"pass": t1_ok, "reason": t1_reason}
    if not t1_ok:
        return False, report

    # Tier 3 (alertas — antes de Tier 2 porque son descarte inmediato)
    t3_alerts = check_tier3_alerts(m)
    report["tier3"] = {"alerts": t3_alerts, "pass": len(t3_alerts) == 0}
    if t3_alerts:
        return False, report

    # Tier 2
    t2_count, t2_results = count_tier2_passes(m)
    t2_ok = t2_count >= C.TIER2_MIN_PASS
    report["tier2"] = {"passed": t2_count, "of": 6, "pass": t2_ok, "details": t2_results}
    if not t2_ok:
        return False, report

    # Bot detection (usa métricas ya calculadas en WalletMetrics)
    bot_tests_passed = 0
    bot_details = []

    # Test 1: Intervalo CV
    ok = m.interval_cv >= C.BOT_INTERVAL_CV_MIN
    bot_tests_passed += int(ok)
    bot_details.append(f"interval_cv={m.interval_cv:.2f} {'✓' if ok else '✗'}")

    # Test 2: Size CV
    ok = m.size_cv >= C.BOT_SIZE_CV_MIN
    bot_tests_passed += int(ok)
    bot_details.append(f"size_cv={m.size_cv:.2f} {'✓' if ok else '✗'}")

    # Test 3: Correlation delay (requiere datos externos — placeholder)
    # Se implementa en bot_detector.py con comparación cross-wallet
    ok = True  # Asumir pass hasta que se implemente cross-wallet
    bot_tests_passed += int(ok)
    bot_details.append("corr_delay=pending ✓")

    # Test 4: Unique markets
    ok = m.unique_markets_pct >= C.BOT_MIN_UNIQUE_MARKETS_PCT
    bot_tests_passed += int(ok)
    bot_details.append(f"unique_mkts={m.unique_markets_pct:.0%} {'✓' if ok else '✗'}")

    # Test 5: No es market maker (frecuencia)
    ok = m.trades_per_month <= C.BOT_MAX_TRADES_PER_MONTH
    bot_tests_passed += int(ok)
    bot_details.append(f"freq={m.trades_per_month:.0f}/mo {'✓' if ok else '✗'}")

    bot_ok = bot_tests_passed >= C.BOT_MIN_TESTS_PASS
    report["bot"] = {"passed": bot_tests_passed, "of": 5, "pass": bot_ok,
                      "details": bot_details}

    final = bot_ok
    report["final"] = final
    return final, report
```

### 1.6 bot_detector.py — Tests avanzados de detección de bots

```python
"""
bot_detector.py — Implementación de los 5 tests de detección de bots.
Los tests 1, 2 y 5 se calculan en wallet_analyzer.
Este módulo implementa el Test 3 (correlación de delay) y Test 4 (originalidad)
que requieren comparar contra OTROS wallets.

MÓDULO COMPARTIDO.
"""
import numpy as np
from collections import defaultdict
from common.data_client import DataClient


def test_delay_correlation(
    target_trades: list[dict],
    whale_trades_by_wallet: dict[str, list[dict]],
    max_delay_seconds: int = 60,
    min_correlation: float = 0.70,
) -> tuple[bool, dict]:
    """
    Test 3: ¿El wallet target opera consistentemente N segundos
    después de otro wallet en los mismos mercados?

    Args:
        target_trades: Trades del wallet que estamos evaluando.
        whale_trades_by_wallet: {wallet_addr: [trades]} de los whales conocidos.
        max_delay_seconds: Ventana máxima de delay para considerar correlación.
        min_correlation: Threshold de correlación para marcar como copier.

    Returns:
        (is_human: bool, details: dict)
    """
    target_by_market = defaultdict(list)
    for t in target_trades:
        target_by_market[t["conditionId"]].append(t["timestamp"])

    correlations = {}
    for whale_addr, whale_trades in whale_trades_by_wallet.items():
        whale_by_market = defaultdict(list)
        for t in whale_trades:
            whale_by_market[t["conditionId"]].append(t["timestamp"])

        # Buscar mercados en común
        common_markets = set(target_by_market.keys()) & set(whale_by_market.keys())
        if len(common_markets) < 3:
            continue

        delays = []
        for mkt in common_markets:
            for t_ts in target_by_market[mkt]:
                # Buscar el trade del whale más cercano ANTES del target
                whale_times = sorted(whale_by_market[mkt])
                for w_ts in whale_times:
                    delay = t_ts - w_ts
                    if 0 < delay <= max_delay_seconds:
                        delays.append(delay)
                        break

        if len(delays) >= 5:
            # Si los delays son muy consistentes (baja varianza),
            # es probable que sea un copier
            cv = np.std(delays) / np.mean(delays) if np.mean(delays) > 0 else 1
            consistency_score = 1 - min(cv, 1)  # 1 = perfectamente consistente
            correlations[whale_addr] = {
                "avg_delay": np.mean(delays),
                "std_delay": np.std(delays),
                "consistency": consistency_score,
                "n_matches": len(delays),
            }

    if not correlations:
        return True, {"result": "no_correlation_found"}

    max_corr_wallet = max(correlations, key=lambda w: correlations[w]["consistency"])
    max_corr = correlations[max_corr_wallet]

    is_human = max_corr["consistency"] < min_correlation
    return is_human, {
        "most_correlated_wallet": max_corr_wallet,
        "consistency_score": max_corr["consistency"],
        "avg_delay_seconds": max_corr["avg_delay"],
        "is_human": is_human,
    }


def test_market_originality(
    target_trades: list[dict],
    whale_markets: set[str],
) -> tuple[bool, float]:
    """
    Test 4: ¿Qué % de los mercados del target NO son operados por whales conocidos?

    Args:
        target_trades: Trades del wallet evaluado.
        whale_markets: Set de conditionIds donde operan los top whales.

    Returns:
        (is_original: bool, pct_unique: float)
    """
    target_markets = set(t["conditionId"] for t in target_trades)
    if not target_markets:
        return False, 0.0

    unique = target_markets - whale_markets
    pct = len(unique) / len(target_markets)
    return pct >= 0.15, pct
```

---

## PARTE 2 — ESTRATEGIA 1: Wallet Basket Consensus

### 2.1 Los 3 baskets iniciales recomendados

Estos son los 3 mercados/categorías más fáciles para construir baskets:

**Basket 1 — Crypto Prices** (tag: crypto)
- Por qué es el más fácil: Mayor volumen, más wallets activos, resolución frecuente (diaria/semanal para BTC price targets).
- Mercados tipo: "BTC above $X by date", "ETH above $X", "SOL above $X".
- Ventaja: Alta liquidez, muchos wallets con historial largo, resolución rápida.
- Riesgo: Dominado por bots — el filtrado de §3 es CRÍTICO aquí.

**Basket 2 — Economía/Fed** (tag: economics)
- Por qué es bueno: Mercados con resolución programada (reuniones FOMC tienen fecha fija), alta liquidez en torno a eventos macro.
- Mercados tipo: "Fed rate cut/hold", "CPI above/below X", "Recession by date".
- Ventaja: Los traders humanos con edge real son analistas macro, más fáciles de distinguir de bots.
- Riesgo: Frecuencia menor de eventos (FOMC es cada ~6 semanas), pero los mercados derivados son frecuentes.

**Basket 3 — Política/Geopolítica** (tag: politics)
- Por qué es bueno: Los insiders políticos tienen edge real y medible, muchos mercados de resolución <7 días en torno a votos legislativos, executive orders, etc.
- Mercados tipo: "Bill passes Senate", "Trump executive order on X", "Government shutdown".
- Ventaja: El consenso de wallets informados es especialmente valioso aquí.
- Riesgo: Mercados pueden ser manipulados por "mention markets" (Elon posts); filtrar estos.

### 2.2 basket_builder.py — Construcción automática de baskets

```python
"""
basket_builder.py — Construye baskets temáticos de wallets.

FLUJO:
1. Usar Gamma API para descubrir mercados activos de una categoría.
2. Para cada mercado top, obtener los top holders (Data API).
3. Recopilar un pool de wallets candidatos (unión de holders).
4. Analizar cada wallet con wallet_analyzer.
5. Filtrar con wallet_filter (pipeline completo).
6. Seleccionar los 5-10 mejores para el basket.

ESPECÍFICO DE ESTRATEGIA 1.
"""
import time
from collections import Counter, defaultdict
from common.gamma_client import GammaClient
from common.data_client import DataClient
from common.wallet_analyzer import analyze_wallet, WalletMetrics
from common.wallet_filter import full_filter_pipeline
from common.bot_detector import test_delay_correlation, test_market_originality
from common import config as C


class BasketBuilder:

    def __init__(self):
        self.gamma = GammaClient()
        self.data = DataClient()

    def build_basket(
        self,
        category: str,
        tag_ids: list[int],
        max_wallets: int = C.BASKET_MAX_WALLETS,
    ) -> dict:
        """
        Construye un basket completo para una categoría.

        Args:
            category: Nombre de la categoría ("crypto", "politics", "economics")
            tag_ids: Lista de tag_ids de Gamma API para esta categoría.

        Returns:
            {
                "category": str,
                "wallets": [WalletMetrics, ...],   # Los seleccionados
                "rejected": [{"address": str, "reason": str}, ...],
                "markets_scanned": int,
                "candidates_found": int,
            }
        """
        print(f"\n{'='*60}")
        print(f"  BUILDING BASKET: {category.upper()}")
        print(f"{'='*60}")

        # ─── Paso 1: Descubrir mercados activos de esta categoría ───
        print(f"\n[1/6] Descubriendo mercados para {category}...")
        markets = []
        for tag_id in tag_ids:
            batch = self.gamma.get_active_markets(
                tag_id=tag_id,
                min_volume_24h=C.MIN_LIQUIDITY_24H,
                limit=50,
            )
            markets.extend(batch)
            time.sleep(0.2)

        # Deduplicar por conditionId
        seen = set()
        unique_markets = []
        for m in markets:
            cid = m.get("conditionId")
            if cid and cid not in seen:
                seen.add(cid)
                unique_markets.append(m)

        # Solo mercados que resuelven en ≤7 días (tu restricción)
        import datetime
        cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=7)
        cutoff_iso = cutoff.isoformat() + "Z"

        short_term = [
            m for m in unique_markets
            if (m.get("endDate") or "9999") <= cutoff_iso
        ]
        # Si no hay suficientes de corto plazo, incluir todos
        target_markets = short_term if len(short_term) >= 5 else unique_markets[:20]

        print(f"   Encontrados: {len(unique_markets)} mercados "
              f"({len(short_term)} resuelven en ≤7d)")

        # ─── Paso 2: Obtener top holders de cada mercado ─────────
        print(f"\n[2/6] Obteniendo top holders...")
        wallet_frequency = Counter()     # wallet → en cuántos mercados aparece
        wallet_markets = defaultdict(set) # wallet → set de conditionIds

        for mkt in target_markets[:15]:  # Limitar a 15 mercados para rate limits
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                holders = self.data.get_market_holders(cid, limit=30)
                for h in holders:
                    addr = h.get("proxyWallet") or h.get("address")
                    if addr:
                        wallet_frequency[addr] += 1
                        wallet_markets[addr].add(cid)
            except Exception as e:
                print(f"   Error en holders de {cid[:16]}...: {e}")
            time.sleep(0.15)

        # Priorizar wallets que aparecen en múltiples mercados de la categoría
        candidates = [
            addr for addr, count in wallet_frequency.most_common(50)
            if count >= 2  # Aparece en al menos 2 mercados de la categoría
        ]
        print(f"   Candidatos con presencia en ≥2 mercados: {len(candidates)}")

        # ─── Paso 3: Obtener trades y analizar cada candidato ────
        print(f"\n[3/6] Analizando wallets candidatos...")
        analyzed = []
        for i, addr in enumerate(candidates[:30]):  # Limitar a 30 para rate limits
            try:
                # Obtener últimos 4 meses de trades
                four_months_ago = int(
                    (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
                )
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    continue
                metrics = analyze_wallet(trades, addr)
                analyzed.append((metrics, trades))
                if (i + 1) % 5 == 0:
                    print(f"   Analizados: {i+1}/{min(len(candidates), 30)}")
            except Exception as e:
                print(f"   Error analizando {addr[:12]}...: {e}")
            time.sleep(0.2)

        print(f"   Wallets con datos suficientes: {len(analyzed)}")

        # ─── Paso 4: Filtrar con pipeline completo ───────────────
        print(f"\n[4/6] Aplicando filtros Tier 1/2/3 + bot detection...")
        passed = []
        rejected = []

        # Recopilar mercados de todos los whales para test de originalidad
        all_whale_markets = set()
        for m, _ in analyzed[:10]:
            for t in _:
                all_whale_markets.add(t.get("conditionId", ""))

        for metrics, trades in analyzed:
            ok, report = full_filter_pipeline(metrics)
            if ok:
                passed.append(metrics)
            else:
                # Encontrar la primera razón de fallo
                for tier in ["tier1", "tier3", "tier2", "bot"]:
                    tier_report = report.get(tier, {})
                    if tier_report and not tier_report.get("pass", True):
                        reason = tier_report.get("reason", str(tier_report))
                        rejected.append({"address": metrics.address, "reason": reason})
                        break

        print(f"   Pasaron filtros: {len(passed)} / {len(analyzed)}")

        # ─── Paso 5: Ranking y selección final ───────────────────
        print(f"\n[5/6] Ranking por score compuesto...")

        def score_wallet(m: WalletMetrics) -> float:
            """
            Score compuesto para ranking dentro del basket.
            Prioriza: profit factor, edge_vs_odds, frecuencia, consistencia.
            """
            return (
                m.profit_factor * 0.30 +
                (m.edge_vs_odds * 100) * 0.25 +
                min(m.trades_per_month / 20, 1) * 0.20 +
                m.positive_weeks_pct * 0.15 +
                (1 - m.is_likely_bot) * 0.10
            )

        scored = sorted(passed, key=score_wallet, reverse=True)
        selected = scored[:max_wallets]

        print(f"\n[6/6] Basket {category}: {len(selected)} wallets seleccionados")
        for i, w in enumerate(selected):
            print(f"   {i+1}. {w.address[:12]}... "
                  f"WR={w.win_rate:.0%} PF={w.profit_factor:.1f} "
                  f"edge={w.edge_vs_odds:.1%} freq={w.trades_per_month:.0f}/mo")

        return {
            "category": category,
            "wallets": selected,
            "rejected": rejected,
            "markets_scanned": len(unique_markets),
            "candidates_found": len(candidates),
        }

    def build_all_baskets(self) -> dict[str, dict]:
        """
        Construye los 3 baskets iniciales.
        Primero descubre los tag_ids actuales de Gamma API.
        """
        print("Descubriendo tag_ids de categorías...")
        tag_map = self.gamma.discover_category_tags()
        print(f"Tags encontrados: { {k: len(v) for k,v in tag_map.items()} }")

        baskets = {}
        for category in ["crypto", "economics", "politics"]:
            tag_ids = tag_map.get(category, [])
            if not tag_ids:
                print(f"⚠️  No se encontraron tags para {category}")
                continue
            basket = self.build_basket(category, tag_ids)
            baskets[category] = basket
            time.sleep(1)  # Pausa entre baskets

        return baskets
```

### 2.3 consensus_engine.py — Motor de consenso

```python
"""
consensus_engine.py — Evalúa señales de consenso dentro de un basket.

Regla: cuando ≥80% de los wallets de un basket toman la misma posición
en el mismo mercado dentro de una ventana de 4 horas → generar señal.

ESPECÍFICO DE ESTRATEGIA 1.
"""
import time
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from common import config as C


@dataclass
class ConsensusSignal:
    """Señal generada por el motor de consenso."""
    basket_category: str
    market_condition_id: str
    market_title: str
    market_slug: str
    outcome: str                  # "Yes" o "No"
    consensus_pct: float          # Ej: 0.83
    wallets_in: list[str]         # Wallets que coinciden
    avg_entry_price: float
    earliest_entry_ts: int
    latest_entry_ts: int
    signal_ts: int                # Cuando se generó la señal
    market_volume_24h: float
    valid: bool = True
    rejection_reason: str = ""


class ConsensusEngine:
    """
    Monitorea las actividades recientes de los wallets de un basket
    y genera señales cuando se alcanza consenso.
    """

    def __init__(self, basket_wallets: list[str], category: str):
        self.wallets = set(basket_wallets)
        self.category = category
        # Almacena trades recientes por mercado
        # {conditionId: {wallet: {"side": "BUY", "outcome": "Yes", "price": 0.65, "ts": ...}}}
        self.recent_positions = defaultdict(dict)

    def ingest_trade(self, trade: dict):
        """
        Ingesta un trade nuevo de uno de los wallets del basket.
        Llamado desde el monitor (websocket o polling).
        """
        wallet = trade.get("proxyWallet")
        if wallet not in self.wallets:
            return

        cid = trade.get("conditionId")
        if not cid:
            return

        self.recent_positions[cid][wallet] = {
            "side": trade.get("side"),
            "outcome": trade.get("outcome"),
            "price": trade.get("price", 0),
            "ts": trade.get("timestamp", int(time.time())),
            "usdcSize": trade.get("usdcSize", 0),
            "title": trade.get("title", ""),
            "slug": trade.get("slug", ""),
        }

    def evaluate_consensus(self) -> list[ConsensusSignal]:
        """
        Evalúa todos los mercados activos buscando consenso.
        Retorna lista de señales que cumplen el threshold.
        """
        signals = []
        now_ts = int(time.time())
        window = C.BASKET_TIME_WINDOW_HOURS * 3600

        for cid, wallet_positions in self.recent_positions.items():
            # Filtrar posiciones dentro de la ventana temporal
            recent = {
                w: pos for w, pos in wallet_positions.items()
                if now_ts - pos["ts"] <= window
            }

            if len(recent) < 2:
                continue

            # Contar votos por outcome
            outcome_votes = defaultdict(list)
            for w, pos in recent.items():
                if pos["side"] == "BUY":
                    outcome_votes[pos["outcome"]].append(w)

            # Evaluar consenso
            total_voters = len(recent)
            for outcome, voters in outcome_votes.items():
                pct = len(voters) / len(self.wallets)  # vs total del basket

                if pct >= C.BASKET_CONSENSUS_THRESHOLD:
                    prices = [recent[w]["price"] for w in voters]
                    timestamps = [recent[w]["ts"] for w in voters]
                    title = recent[voters[0]].get("title", "")
                    slug = recent[voters[0]].get("slug", "")

                    signal = ConsensusSignal(
                        basket_category=self.category,
                        market_condition_id=cid,
                        market_title=title,
                        market_slug=slug,
                        outcome=outcome,
                        consensus_pct=pct,
                        wallets_in=voters,
                        avg_entry_price=sum(prices) / len(prices),
                        earliest_entry_ts=min(timestamps),
                        latest_entry_ts=max(timestamps),
                        signal_ts=now_ts,
                        market_volume_24h=0,  # Se llena en validación
                    )
                    signals.append(signal)

        return signals

    def cleanup_old_positions(self, max_age_hours: int = 24):
        """Limpia posiciones más antiguas que max_age_hours."""
        cutoff = int(time.time()) - max_age_hours * 3600
        for cid in list(self.recent_positions.keys()):
            self.recent_positions[cid] = {
                w: pos for w, pos in self.recent_positions[cid].items()
                if pos["ts"] >= cutoff
            }
            if not self.recent_positions[cid]:
                del self.recent_positions[cid]
```

---

## PARTE 3 — ESTRATEGIA 2: Scalper Rotator

### 3.1 pool_builder.py — Construir pool de candidatos

```python
"""
pool_builder.py — Construye el pool de 8-12 wallets para Scalper Rotator.

Diferencias con basket_builder:
- NO agrupa por categoría — busca los mejores traders cross-category.
- Filtra por holding period más agresivo (1-5 días vs 1-7).
- Requiere frecuencia más alta (≥12 trades/mes vs ≥8).
- Ranking prioriza Sharpe ratio sobre consenso.

ESPECÍFICO DE ESTRATEGIA 2.
"""
import time
import datetime
import numpy as np
from common.gamma_client import GammaClient
from common.data_client import DataClient
from common.wallet_analyzer import analyze_wallet, WalletMetrics
from common.wallet_filter import full_filter_pipeline
from common import config as C


class ScalperPoolBuilder:

    def __init__(self):
        self.gamma = GammaClient()
        self.data = DataClient()

    def build_pool(self, pool_size: int = C.SCALPER_POOL_SIZE) -> dict:
        """
        Construye el pool de wallets para la estrategia Scalper.

        Flujo:
        1. Obtener top mercados por volumen (cross-category).
        2. Obtener holders y traders recientes de esos mercados.
        3. Filtrar con pipeline estándar + filtros Scalper específicos.
        4. Rankear por estimated Sharpe y seleccionar top N.
        """
        print(f"\n{'='*60}")
        print(f"  BUILDING SCALPER POOL (target: {pool_size} wallets)")
        print(f"{'='*60}")

        # ─── Paso 1: Top mercados cross-category ─────────────────
        print("\n[1/5] Descubriendo top mercados por volumen...")
        markets = self.gamma.get_active_markets(
            min_volume_24h=C.MIN_LIQUIDITY_24H,
            limit=100,
        )
        print(f"   {len(markets)} mercados con ≥${C.MIN_LIQUIDITY_24H:,} vol 24h")

        # ─── Paso 2: Recopilar wallets activos ───────────────────
        print("\n[2/5] Recopilando wallets activos...")
        from collections import Counter
        wallet_freq = Counter()

        for mkt in markets[:20]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            try:
                # Usar trades recientes en lugar de holders
                trades = self.data.get_market_trades(cid, limit=200)
                for t in trades:
                    addr = t.get("proxyWallet")
                    if addr:
                        wallet_freq[addr] += 1
            except Exception as e:
                print(f"   Error: {e}")
            time.sleep(0.15)

        candidates = [addr for addr, _ in wallet_freq.most_common(60)]
        print(f"   Candidatos únicos: {len(candidates)}")

        # ─── Paso 3: Analizar y filtrar ──────────────────────────
        print("\n[3/5] Analizando wallets...")
        analyzed = []
        four_months_ago = int(
            (datetime.datetime.utcnow() - datetime.timedelta(days=120)).timestamp()
        )

        for i, addr in enumerate(candidates[:40]):
            try:
                trades = self.data.get_all_wallet_trades(addr, start=four_months_ago)
                if len(trades) < C.MIN_TRADES_TOTAL:
                    continue
                metrics = analyze_wallet(trades, addr)

                # Filtros ESPECÍFICOS de Scalper (más agresivos)
                if metrics.avg_holding_period_hours > 5 * 24:  # Max 5 días
                    continue
                if metrics.trades_per_month < 12:  # Min 12/mes
                    continue

                analyzed.append((metrics, trades))
            except Exception:
                pass
            time.sleep(0.2)

        print(f"   Pasan filtros específicos Scalper: {len(analyzed)}")

        # ─── Paso 4: Pipeline estándar ───────────────────────────
        print("\n[4/5] Aplicando pipeline de filtros estándar...")
        passed = []
        for metrics, trades in analyzed:
            ok, report = full_filter_pipeline(metrics)
            if ok:
                passed.append((metrics, trades))

        print(f"   Pasan pipeline completo: {len(passed)}")

        # ─── Paso 5: Ranking por estimated Sharpe ────────────────
        print("\n[5/5] Ranking por Sharpe estimado...")

        def estimate_sharpe(metrics: WalletMetrics, trades: list[dict]) -> float:
            """
            Estima Sharpe ratio de los últimos 14 días.
            Sharpe = mean(daily_returns) / std(daily_returns) * sqrt(365)
            """
            now_ts = int(time.time())
            ts_14d = now_ts - 14 * 86400
            recent = [t for t in trades if t["timestamp"] >= ts_14d]
            if len(recent) < 5:
                return 0.0

            # Agrupar P&L por día
            from collections import defaultdict
            daily_pnl = defaultdict(float)
            for t in recent:
                day = datetime.datetime.utcfromtimestamp(t["timestamp"]).date()
                usdc = t.get("usdcSize", 0)
                if t.get("side") == "SELL":
                    daily_pnl[day] += usdc
                else:
                    daily_pnl[day] -= usdc

            if len(daily_pnl) < 3:
                return 0.0

            returns = list(daily_pnl.values())
            mean_r = np.mean(returns)
            std_r = np.std(returns)
            if std_r == 0:
                return 0.0
            return (mean_r / std_r) * np.sqrt(365)

        scored = []
        for metrics, trades in passed:
            sharpe = estimate_sharpe(metrics, trades)
            scored.append((metrics, sharpe))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [(m, s) for m, s in scored[:pool_size]]

        print(f"\n   Pool final: {len(selected)} wallets")
        for i, (m, sharpe) in enumerate(selected):
            print(f"   {i+1}. {m.address[:12]}... "
                  f"Sharpe={sharpe:.2f} WR={m.win_rate:.0%} "
                  f"freq={m.trades_per_month:.0f}/mo")

        return {
            "wallets": [m for m, _ in selected],
            "sharpe_scores": {m.address: s for m, s in selected},
            "pool_size": len(selected),
        }
```

### 3.2 rotation_engine.py — Selección semanal por Sharpe

```python
"""
rotation_engine.py — Selección semanal de "titulares" activos.

Cada lunes 00:00 UTC:
1. Recalcular Sharpe 14d para todo el pool.
2. Seleccionar top 2-3 como titulares.
3. Retirar wallets en cuarentena.
4. Reportar cambios.

ESPECÍFICO DE ESTRATEGIA 2.
"""
import time
import datetime
import numpy as np
from dataclasses import dataclass
from common import config as C


@dataclass
class RotationResult:
    """Resultado de una rotación semanal."""
    timestamp: int
    new_titulars: list[str]       # Wallets que entran como titulares
    removed_titulars: list[str]   # Wallets que salen
    quarantined: list[str]        # Wallets en cuarentena
    sharpe_scores: dict[str, float]
    capital_allocation: dict[str, float]  # wallet → % de capital


class RotationEngine:

    def __init__(self, pool_wallets: list[str], pool_sharpe: dict[str, float]):
        self.pool = set(pool_wallets)
        self.sharpe = pool_sharpe
        self.titulars = []
        self.quarantine = {}     # wallet → expiry_timestamp
        self.loss_streaks = {}   # wallet → consecutive_losses

    def execute_rotation(
        self,
        current_sharpe_14d: dict[str, float],
        wallet_pnl_7d: dict[str, float],
        wallet_pnl_14d: dict[str, float],
        total_capital: float,
    ) -> RotationResult:
        """
        Ejecutar rotación semanal.

        Args:
            current_sharpe_14d: {wallet: sharpe} actualizado.
            wallet_pnl_7d: {wallet: pnl_usd} últimos 7 días.
            wallet_pnl_14d: {wallet: pnl_usd} últimos 14 días.
            total_capital: Capital total disponible.
        """
        now_ts = int(time.time())

        # 1. Limpiar cuarentenas expiradas
        self.quarantine = {
            w: exp for w, exp in self.quarantine.items()
            if exp > now_ts
        }

        # 2. Verificar reglas de expulsión de titulares actuales
        removed = []
        for w in list(self.titulars):
            # 2 semanas P&L negativo → bench
            if wallet_pnl_7d.get(w, 0) < 0 and wallet_pnl_14d.get(w, 0) < 0:
                removed.append(w)
                self.titulars.remove(w)

        # 3. Pool elegible (excluir cuarentena)
        eligible = [
            w for w in self.pool
            if w not in self.quarantine
        ]

        # 4. Ranking por Sharpe
        ranked = sorted(
            eligible,
            key=lambda w: current_sharpe_14d.get(w, -999),
            reverse=True,
        )

        # 5. Seleccionar top N
        n = C.SCALPER_ACTIVE_WALLETS
        new_titulars = ranked[:n]
        self.titulars = new_titulars

        # 6. Asignar capital equitativamente
        per_wallet = total_capital / n if n > 0 else 0
        allocation = {w: per_wallet for w in new_titulars}

        return RotationResult(
            timestamp=now_ts,
            new_titulars=new_titulars,
            removed_titulars=removed,
            quarantined=list(self.quarantine.keys()),
            sharpe_scores=current_sharpe_14d,
            capital_allocation=allocation,
        )

    def quarantine_wallet(self, wallet: str, days: int = C.QUARANTINE_LOSS_DAYS):
        """Pone un wallet en cuarentena."""
        self.quarantine[wallet] = int(time.time()) + days * 86400
        if wallet in self.titulars:
            self.titulars.remove(wallet)

    def register_loss(self, wallet: str, loss_pct: float):
        """
        Registra una pérdida. Si hay 3 consecutivas de >10%,
        → cuarentena automática.
        """
        if loss_pct < -0.10:
            self.loss_streaks[wallet] = self.loss_streaks.get(wallet, 0) + 1
            if self.loss_streaks[wallet] >= C.SCALPER_CONSECUTIVE_LOSS_LIMIT:
                self.quarantine_wallet(wallet)
                self.loss_streaks[wallet] = 0
        else:
            self.loss_streaks[wallet] = 0
```

---

## PARTE 4 — RESUMEN DE SEPARACIÓN COMÚN vs ESPECÍFICO

| Módulo | Estrategia 1 (Basket) | Estrategia 2 (Scalper) | Compartido |
|---|---|---|---|
| `config.py` | — | — | ✅ |
| `gamma_client.py` | ✅ usa tags | ✅ usa top markets | ✅ |
| `data_client.py` | ✅ holders + activity | ✅ trades + activity | ✅ |
| `wallet_analyzer.py` | ✅ | ✅ | ✅ |
| `wallet_filter.py` | ✅ | ✅ | ✅ |
| `bot_detector.py` | ✅ | ✅ | ✅ |
| `risk_manager.py` | ✅ | ✅ | ✅ |
| `basket_builder.py` | ✅ | — | Solo Basket |
| `consensus_engine.py` | ✅ | — | Solo Basket |
| `pool_builder.py` | — | ✅ | Solo Scalper |
| `rotation_engine.py` | — | ✅ | Solo Scalper |

### Diferencias clave en filtros:

| Criterio | Basket | Scalper |
|---|---|---|
| Holding period max | 7 días | 5 días |
| Frecuencia mínima | 8 trades/mes | 12 trades/mes |
| Agrupación | Por categoría temática | Cross-category |
| Selección | Score compuesto | Sharpe ratio 14d |
| Cuántos activos | 5-10 por basket × 3 baskets | 2-3 titulares de pool de 12 |
| Señal de entrada | 80% consenso del basket | Copia directa del titular |
| Rotación | Solo retirada por underperformance | Semanal por ranking |

---

## PARTE 5 — requirements.txt

```
py-clob-client>=0.34
polymarket-apis>=0.5
requests>=2.31
numpy>=1.24
python-dotenv>=1.0
websocket-client>=1.6
```

---

## PARTE 6 — ORDEN DE IMPLEMENTACIÓN

**Sprint 1 (Semana 1): Data pipeline + filtros**
1. `config.py` — constantes
2. `gamma_client.py` — descubrimiento de mercados
3. `data_client.py` — trades y posiciones
4. `wallet_analyzer.py` — cálculo de métricas
5. `wallet_filter.py` — pipeline de filtros
6. Test: ejecutar `basket_builder.build_all_baskets()` y verificar output

**Sprint 2 (Semana 2): Elegir UNA estrategia para MVP**
- Si Basket: `basket_builder.py` + `consensus_engine.py`
- Si Scalper: `pool_builder.py` + `rotation_engine.py`

**Sprint 3 (Semana 3): Risk + ejecución**
1. `risk_manager.py` — circuit breakers
2. Conectar CLOB API para ejecución de trades
3. Test con $1-5 por trade en producción (no hay testnet)

**Sprint 4 (Semana 4): Monitoring + segunda estrategia**
1. Alertas (Telegram/Discord)
2. PnL tracking
3. Implementar la segunda estrategia

---

*Kaizen Trading System — Implementación Guide v1.0 — Abril 2026*
