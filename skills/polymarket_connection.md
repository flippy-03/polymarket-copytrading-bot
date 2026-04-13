# SKILL: polymarket-connection — v2.0 — 2026-04-12

**Propósito**: Referencia completa y autocontenida para conectar CUALQUIER sistema de trading o bot a Polymarket. No asume ningún framework ni estructura de proyecto — copia solo las secciones que necesites.

**Contenido**:
1. [Mapa de APIs](#1-mapa-de-apis)
2. [APIs: Gamma, CLOB, Data, PolymarketScan](#2-apis)
3. [Configuración — variables de entorno](#3-configuración)
4. [Patrones de código — snippets validados en producción](#4-patrones-de-código)
5. [Lecciones críticas — 17 bugs reales](#5-lecciones-críticas)
6. [Herramientas complementarias](#6-herramientas-complementarias)

---

## 1. Mapa de APIs

| QUIERO... | USA |
|-----------|-----|
| Descubrir mercados activos por categoría | Gamma API |
| Obtener el token_id de un mercado | Gamma API |
| Leer el orderbook en tiempo real | CLOB API |
| Colocar / cancelar una orden | CLOB API (auth) |
| Ver mis posiciones y balance | CLOB API (auth) |
| Historial de trades de cualquier wallet | Data API |
| Precios históricos de probabilidad de un mercado | Data API |
| Top traders por PnL / volumen / ROI | Data API o PMScan |
| Feed de ballenas en tiempo real | PolymarketScan o Falcon (556) |
| Divergencia entre AI y mercado humano | PolymarketScan |
| Paper trading en arena virtual ($1,000 USDC) | PolymarketScan Arena |
| Perfil PnL de un trader específico con Sharpe | PolymarketScan o Falcon (581) |
| Concentración de whales / whale herding | Falcon MCP (575) |
| Volume trend + squeeze risk de un mercado | Falcon MCP (575) |
| Qué lado está ganando dinero en un mercado | Falcon MCP (575) — `winning_side` |
| Trades OHLC históricos de un token | Falcon MCP (568) |
| Saltos de precio bruscos en tiempo real | Falcon MCP (596) |
| Ranking H-Score de smart money wallets | Falcon MCP (584) |

---

## 2. APIs

### A. Gamma API

| Campo | Valor |
|-------|-------|
| Tipo | Oficial Polymarket |
| Base URL | `https://gamma-api.polymarket.com` |
| Auth | Ninguna — pública |
| Uso principal | Discovery de mercados. Devuelve los `clobTokenIds` para consultar el orderbook en CLOB API. |

**Endpoints:**

| Endpoint | Método | Parámetros clave |
|----------|--------|-----------------|
| `/markets` | GET | `tag` (Crypto\|Politics\|Sports), `closed=false`, `order` (startDate\|endDate), `ascending` (true\|false), `limit=200` |
| `/markets/{conditionId}` | GET | — |
| `/events` | GET | Agrupa mercados relacionados (ej: "BTC price this week") |

**Campos clave de la respuesta:**

| Campo | Notas |
|-------|-------|
| `conditionId` | ID único del mercado. Úsalo como `market_id` en todo el sistema. ⚠️ NO sirve para consultar el orderbook (CLOB necesita `token_id`). |
| `clobTokenIds` | ⚠️ **[GOTCHA #1]** Es un STRING JSON, no un array. SIEMPRE aplicar `json.loads()` antes de indexar. `[0]` = token YES, `[1]` = token NO (raramente tiene liquidez — ver gotcha #3). |
| `question` | Texto del mercado en mayúsculas. Ej: `"BITCOIN UP OR DOWN - APRIL 12"` |
| `endDate` | ISO 8601 con Z. Convertir: `datetime.fromisoformat(x.replace('Z','+00:00'))` |
| `startDate` | Fecha de apertura del mercado |
| `closed` | boolean. Filtrar `closed=false` para mercados activos |

**Discovery dual-query (patrón obligatorio):**

> ⚠️ **[GOTCHA #4]** Con una sola query (`order=startDate desc`) solo encuentras mercados recién abiertos con TTL ~24h. Si redescubres cada hora, los reemplazas ANTES de que lleguen a la ventana de entrada (últimos 45-90s). Solución: dos queries merged por `conditionId`.

```python
import json, httpx
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"

async def discover_markets(tag: str = "Crypto") -> list[dict]:
    urls = [
        f"{GAMMA}/markets?tag={tag}&closed=false&order=startDate&ascending=false&limit=200",
        f"{GAMMA}/markets?tag={tag}&closed=false&order=endDate&ascending=true&limit=200",
    ]
    all_raw = []
    async with httpx.AsyncClient(timeout=30.0) as http:
        for url in urls:
            resp = await http.get(url)
            resp.raise_for_status()
            all_raw.extend(resp.json())

    # Deduplicar por conditionId
    seen, data = set(), []
    for m in all_raw:
        cid = m.get("conditionId")
        if cid and cid not in seen:
            seen.add(cid)
            data.append(m)

    now = datetime.now(timezone.utc).timestamp()
    markets = []
    for m in data:
        if m.get("closed", True):
            continue
        end_raw = m.get("endDate", "")
        try:
            end_ts = int(datetime.fromisoformat(end_raw.replace("Z", "+00:00")).timestamp())
            if end_ts <= now:
                continue
        except (TypeError, ValueError):
            continue
        # ⚠️ GOTCHA #1: clobTokenIds es string JSON
        clob_raw  = m.get("clobTokenIds") or "[]"
        token_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
        if not token_ids:
            continue
        markets.append({
            "market_id": m["conditionId"],
            "token_id":  token_ids[0],   # YES token siempre
            "question":  m.get("question", ""),
            "end_ts":    end_ts,
            "ttl_s":     int(end_ts - now),
        })
    return markets
```

**Rate limits**: Sin límite estricto en producción. Rediscovery máximo cada 3600s.

---

### B. CLOB API

| Campo | Valor |
|-------|-------|
| Tipo | Oficial Polymarket |
| Base URL | `https://clob.polymarket.com` |
| SDK Python | `py-clob-client` (`pip install py-clob-client`) |
| Chain ID | `137` (Polygon mainnet — no cambiar) |

**Niveles de autenticación:**

| Nivel | Descripción | Variables requeridas | Fuente |
|-------|-------------|---------------------|--------|
| 0 — Público | Sin credenciales. Leer orderbooks y mercados públicos. | Ninguna | — |
| 1 — Autenticado | Ver órdenes propias, historial personal. | `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE` | polymarket.com → Settings → API Keys → Generate. **Solo se muestran UNA vez — guardar inmediatamente.** |
| 2 — Trading | Firmar transacciones onchain. | `POLY_PRIVATE_KEY` | MetaMask → Account Details → Export Private Key. ⚠️ NUNCA commitear. |

**Inicialización:**

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
import os

HOST = "https://clob.polymarket.com"

def get_clob_client(authenticated: bool = False) -> ClobClient:
    if not authenticated:
        # Nivel 0 — solo lectura pública
        return ClobClient(host=HOST, chain_id=137)

    creds = ApiCreds(
        api_key=os.getenv("POLY_API_KEY"),
        api_secret=os.getenv("POLY_API_SECRET"),
        api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
    )
    return ClobClient(
        host=HOST,
        key=os.getenv("POLY_PRIVATE_KEY"),   # None si solo lectura autenticada
        chain_id=137,
        creds=creds,
    )
```

**Operaciones clave:**

```python
from py_clob_client.clob_types import TradeParams

# ⚠️ GOTCHA #2: /book necesita token_id, NO condition_id
book = client.get_order_book(token_id)

# El objeto OrderBookSummary NO es un dict — es un objeto con atributos
# .bids y .asks son listas de objetos con .price y .size como strings
best_bid = float(book.bids[0].price) if book.bids else None
best_ask = float(book.asks[0].price) if book.asks else None

# Trades — requiere objeto TradeParams, no kwargs
trades = client.get_trades(TradeParams(market=condition_id))
```

**Rate limits**: 60 requests / 10 segundos.

```python
import asyncio
POLL_INTERVAL = 5.0   # segundos entre polls por mercado
backoff = 1.0
try:
    book = client.get_order_book(token_id)
    backoff = 1.0
except Exception:
    await asyncio.sleep(backoff)
    backoff = min(backoff * 2, 60.0)
```

---

### C. Data API

| Campo | Valor |
|-------|-------|
| Tipo | Oficial Polymarket |
| Base URL | `https://data-api.polymarket.com` |
| Auth | Ninguna — pública |
| Uso principal | Analytics on-chain: posiciones, historial de trades, leaderboards, precios históricos. Ideal para backtesting y análisis de smart money. |

**Endpoints:**

| Endpoint | Parámetros | Uso |
|----------|-----------|-----|
| `GET /positions` | `market=condition_id`, `user=wallet_address` | Posiciones abiertas en un mercado (propias o de cualquier wallet) |
| `GET /trades` | `market=condition_id`, `user=wallet_address`, `limit=100` | Historial de trades más completo que el CLOB |
| `GET /prices-history` | `market=condition_id`, `interval=1m\|5m\|1h\|1d` | Velas de probabilidad histórica — esencial para replay/backtest |
| `GET /leaderboard` | — | Top traders por PnL — punto de partida para analizar smart money |

---

### D. PolymarketScan Agent API

| Campo | Valor |
|-------|-------|
| Tipo | Terceros (analytics) |
| Web | https://polymarketscan.org |
| Base URL | `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api` |
| Skill doc | https://polymarketscan.org/skill.md |
| Auth pública | Sin auth. 60 req/min, caché 60s. Todos los endpoints GET son libres. |
| Auth premium | Header `X-PSK-Key: psk_...`. Desbloquea tier premium, mayor rate limit, webhooks. Guardar en `POLYMARKETSCAN_API_KEY`. |

**Endpoints GET:**

```
# Mercados con filtros
GET ?action=markets&category=Crypto&sort=volume_usd&order=desc&limit=50

# Mercado individual
GET ?action=market&slug=SLUG
GET ?action=market&id=MARKET_ID

# Búsqueda por texto
GET ?action=search&q=bitcoin

# Top traders
GET ?action=leaderboard&type=pnl|volume|roi&limit=20

# ⭐ Divergencia AI vs mercado humano — señal de edge
GET ?action=ai-vs-humans&limit=20

# Perfil y PnL de cualquier wallet (incluye Sharpe ratio, win rate)
GET ?action=trader&wallet=0x...
GET ?action=wallet_trades&wallet=0x...&limit=100
GET ?action=wallet_pnl&wallet=0x...

# Feed de ballenas en tiempo real ($5K+ trades)
GET ?action=whales&limit=20

# Estadísticas globales del sitio
GET ?action=stats

# Arena (paper trading) — portfolio del agente
GET ?action=my_portfolio&agent_id=TU_BOT_ID
GET ?action=arena_leaderboard&limit=20
GET ?action=arena_recent_trades&limit=20
```

**Endpoints POST:**

```json
# Colocar orden en Arena (paper trading — $1,000 USDC virtual)
POST ?action=place_order
Body:
{
  "agent_id":   "TU_BOT_ID",
  "market_id":  "0xCONDITION_ID",
  "side":       "YES",
  "amount":     50,
  "action":     "BUY",
  "fair_value": 0.65
}

# Registrar wallet de pago para recompensas del Arena
POST ?action=set_payout_wallet
Header: X-PSK-Key: psk_...
Body:
{
  "agent_id":      "TU_BOT_ID",
  "payout_wallet": "0xTU_WALLET_ADDRESS"
}
# Respuesta: {"ok":true,"message":"Payout wallet set to 0x... for agent TU_BOT_ID. If you win the arena, rewards will be sent here."}
# ⚠️ GOTCHA: el campo es "payout_wallet", no "wallet"
```

**Campos de respuesta — mercado:**

| Campo | Descripción |
|-------|------------|
| `market_id` | ID numérico interno de PolymarketScan |
| `title` | Nombre del mercado |
| `slug` | Slug → `polymarketscan.org/market/{slug}` |
| `yes_price` | Precio token YES (0-1) |
| `no_price` | Precio token NO (0-1) |
| `volume_usd` | Volumen total acumulado |
| `liquidity_usd` | Liquidez actual del orderbook |
| `volume_24h` | Volumen en las últimas 24h |
| `smart_money_bias` | Score de sesgo de smart money (ballenas) |
| `whale_count` | Ballenas activas en este mercado |
| `closes_at` | ISO 8601 — fecha de resolución |
| `is_resolved` | boolean |
| `price_24h_change` | Cambio de precio en 24h |

**Campos de respuesta — `ai-vs-humans`:**

| Campo | Descripción |
|-------|------------|
| `aiConsensus` | Probabilidad consenso de IAs (0-1) |
| `polymarketPrice` | Precio actual en Polymarket (0-1) |
| `divergence` | Diferencia absoluta — cuanto mayor, más edge potencial |
| `divergenceDirection` | `"bullish"` \| `"bearish"` |

**Cliente Python:**

```python
import httpx, os

BASE     = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api"
PSK_KEY  = os.getenv("POLYMARKETSCAN_API_KEY", "")
AGENT_ID = os.getenv("POLYMARKETSCAN_AGENT_ID", "MiBot")

async def pmscan_get(action: str, **params) -> dict:
    """GET genérico a PolymarketScan Agent API."""
    params["action"]   = action
    params["agent_id"] = AGENT_ID
    headers = {"X-PSK-Key": PSK_KEY} if PSK_KEY else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(BASE, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"PMScan error: {data.get('error')}")
        return data["data"]

async def pmscan_arena_order(
    market_id: str,
    side: str,
    amount: float,
    action: str = "BUY",
    fair_value: float | None = None,
) -> dict:
    """Colocar orden simulada en el Arena de PolymarketScan."""
    body = {
        "agent_id": AGENT_ID,
        "market_id": market_id,
        "side": side,       # "YES" | "NO"
        "amount": amount,
        "action": action,   # "BUY" | "SELL"
    }
    if fair_value is not None:
        body["fair_value"] = fair_value
    headers = {"X-PSK-Key": PSK_KEY} if PSK_KEY else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BASE}?action=place_order&agent_id={AGENT_ID}",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

# ── Ejemplos de uso ──
markets    = await pmscan_get("markets", category="Crypto", sort="volume_usd", limit=20)
divergence = await pmscan_get("ai-vs-humans", limit=20)
whales     = await pmscan_get("whales", limit=10)
pnl        = await pmscan_get("wallet_pnl", wallet="0xADDRESS")
portfolio  = await pmscan_get("my_portfolio")
result     = await pmscan_arena_order("0xCONDITION_ID", "YES", 50, fair_value=0.65)
```

---

## 3. Configuración

> Copiar al `.env` del proyecto. **NUNCA commitear `.env`.**
> Usar `.env.example` (sin valores) como template en el repositorio.

**Template `.env`:**

```env
# Polymarket — CLOB API
POLY_CHAIN_ID=137
POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=
POLY_PRIVATE_KEY=        # solo para trading real

# PolymarketScan Analytics
POLYMARKETSCAN_API_KEY=  # psk_... opcional
POLYMARKETSCAN_AGENT_ID= # nombre de tu bot
```

**Variables:**

| Variable | Fuente | Requerido |
|----------|--------|-----------|
| `POLY_CHAIN_ID` | Valor fijo: `137` (Polygon mainnet) | Siempre |
| `POLY_API_KEY` | polymarket.com → Settings → API Keys → Generate | Solo nivel 1 (auth) |
| `POLY_API_SECRET` | Generado junto con `POLY_API_KEY` | Solo nivel 1 (auth) |
| `POLY_API_PASSPHRASE` | Se elige al crear las API Keys en el dashboard | Solo nivel 1 (auth) |
| `POLY_PRIVATE_KEY` | MetaMask → Account Details → Export Private Key (hex) | Solo `DRY_RUN=false` |
| `POLYMARKETSCAN_API_KEY` | dashboard polymarketscan.org (clave `psk_...`) | No — API pública funciona sin ella |
| `POLYMARKETSCAN_AGENT_ID` | Nombre de tu bot — permanente | No |

> ⚠️ Las API Keys de Polymarket se muestran **una sola vez** al generarlas — copiarlas inmediatamente.
> ⚠️ `POLY_PRIVATE_KEY`: `chmod 600` en servidor. Nunca en código ni logs.

**Setup paso a paso:**

1. `polymarket.com` → conectar wallet Polygon (MetaMask u otra)
2. Settings → API Keys → Generate → copiar KEY, SECRET y PASSPHRASE al `.env`
3. *(si necesitas trading real)* MetaMask → Account Details → Export → copiar `POLY_PRIVATE_KEY`
4. Verificar: `POLY_CHAIN_ID=137`
5. Test read-only (sin credenciales):
   ```bash
   python -c "from py_clob_client.client import ClobClient; c=ClobClient(host='https://clob.polymarket.com', chain_id=137); print('OK')"
   ```
6. *(opcional)* Registrar en polymarketscan.org para obtener `psk_key` premium

---

## 4. Patrones de Código

### Parsear orderbook

```python
# OrderBookSummary de py-clob-client es un OBJETO, no un dict.
# .bids y .asks son listas de objetos con .price y .size como strings.

def parse_orderbook(book) -> dict:
    """Retorna best_bid, best_ask, spread, midpoint o None si vacío."""
    if hasattr(book, "bids"):
        def _p(item): return float(item.price if hasattr(item, "price") else item["price"])
        def _s(item): return float(item.size  if hasattr(item, "size")  else item["size"])
        raw_bids, raw_asks = book.bids or [], book.asks or []
    else:
        def _p(item): return float(item["price"])
        def _s(item): return float(item["size"])
        raw_bids = book.get("bids", [])
        raw_asks = book.get("asks", [])

    bids = sorted(raw_bids, key=_p, reverse=True)
    asks = sorted(raw_asks, key=_p)

    best_bid = _p(bids[0]) if bids else None
    best_ask = _p(asks[0]) if asks else None

    # ⚠️ midpoint es None si el orderbook está vacío — siempre verificar
    midpoint = round((best_bid + best_ask) / 2, 4) if (best_bid and best_ask) else None
    spread   = round(best_ask - best_bid, 4) if (best_bid and best_ask) else None

    bid_depth = sum(_s(b) for b in bids[:3]) if bids else None
    ask_depth = sum(_s(a) for a in asks[:3]) if asks else None

    return {
        "best_bid":      best_bid,
        "best_ask":      best_ask,
        "midpoint":      midpoint,
        "spread":        spread,
        "bid_depth_top3": round(bid_depth, 2) if bid_depth else None,
        "ask_depth_top3": round(ask_depth, 2) if ask_depth else None,
    }
```

### midpoint safe — [GOTCHA #5]

```python
# ⚠️ .get("midpoint", 0) NO protege cuando la clave existe con valor None.
# dict.get("key", default) solo usa el default si la clave NO existe.
# Si el orderbook está vacío, midpoint existe pero vale None → TypeError en comparaciones.

# MAL (crashea silenciosamente con orderbook vacío):
mid = quote.get("midpoint", 0)
if mid > 0.5: ...   # TypeError: '>' not supported between 'NoneType' and 'float'

# BIEN:
mid = quote.get("midpoint")
if mid is None:
    return None     # orderbook vacío — sin precio fiable
```

### Filtrar assets con Gamma API

```python
# Gamma API usa nombres completos: "BITCOIN", "ETHEREUM", "SOLANA"
# Usar word boundaries para evitar falsos positivos (ej: "SOLANA" en "ISOLANA")
import re

ASSETS = {
    "BTC": ["BTC", "BITCOIN"],
    "ETH": ["ETH", "ETHEREUM"],
    "SOL": ["SOL", "SOLANA"],
}

def detect_asset(question: str) -> str | None:
    q = question.upper()
    for ticker, names in ASSETS.items():
        if any(re.search(r'\b' + n + r'\b', q) for n in names):
            return ticker
    return None
```

### Token YES siempre — [GOTCHA #3]

```python
# ⚠️ El token NO raramente tiene liquidez.
# Para señales DOWN: usar el token YES e INVERTIR el umbral.

token_id = token_ids[0]   # YES/UP token siempre
quote = get_quote(token_id)
mid   = quote["midpoint"]

# Interpretar mid según dirección:
#   direction=UP:   edge cuando mid < umbral (mercado subvalora UP)
#   direction=DOWN: edge cuando mid > 1-umbral (mercado no descuenta la bajada)
```

### Ventana de entrada en epoch markets — [GOTCHA #6]

```python
# ⚠️ TTL de epoch markets ≠ duración de la señal.
# "Bitcoin UP or DOWN - April 12, 4:30PM-4:35PM ET" abre 24h ANTES.
# La resolución ocurre en la vela de 5min de las 4:30PM.
# El margen de entrada son los últimos segundos antes del endDate.

# Ventanas típicas para epoch markets de 5min/15min:
ENTRY_WINDOW_MR_START = 90    # mean reversion: entrar entre 90s y 45s antes
ENTRY_WINDOW_MR_END   = 45
ENTRY_WINDOW_TF_START = 600   # trend following: entrar entre 10min y 5min antes
ENTRY_WINDOW_TF_END   = 300

import time
ttl = int(market["end_ts"] - time.time())
in_window = ENTRY_WINDOW_TF_END <= ttl <= ENTRY_WINDOW_TF_START
```

---

## 5. Lecciones Críticas

> 17 bugs reales en producción. Léelos antes de implementar.
> El tag `[GOTCHA #N]` vincula cada lección con el patrón de código en la sección 4.

| ID | Área | Título |
|----|------|--------|
| L-01 | CLOB API | `active=true` en CLOB NO devuelve epoch markets |
| L-02 | CLOB API | `get_order_book()` necesita `token_id`, no `condition_id` |
| L-03 | Gamma API | `clobTokenIds` es un string JSON, no un array |
| L-04 | Gamma API | TTL de epoch markets ≈ 24h — la señal está en los últimos segundos |
| L-05 | Gamma API | Discovery con single-query pierde mercados near-expiry |
| L-06 | CLOB API | Solo token YES tiene liquidez real |
| L-07 | Signal/código | `midpoint None` causa `TypeError` silencioso |
| L-08 | py-clob-client | `OrderBookSummary` es un objeto Python, no un dict |
| L-09 | py-clob-client | `get_trades()` requiere objeto `TradeParams`, no kwargs |
| L-10 | CLOB API | Rate limit: 60 req/10s — sin delay crashea con 429 |
| L-11 | Gamma API | `endDate` viene como string ISO 8601 con `Z`, no como timestamp |
| L-12 | Gamma API | Mercados con `conditionId` None o `clobTokenIds` vacíos — defensividad obligatoria |
| L-13 | py-clob-client / indicadores | Indicadores devuelven `None` si hay pocas velas |
| L-14 | py-clob-client | Parámetros con nombre incorrecto causan fallos silenciosos |
| L-15 | Signal/lógica | Acceder a `metadata` en lugar de `.value` en resultado de indicador |
| L-16 | Gamma API | Mercados long-duration sin filtro de TTL máximo contaminan el pipeline |
| L-17 | py-clob-client | `get_trades()` puede requerir auth (401/403) según el mercado |

---

**L-01 — `active=true` en CLOB NO devuelve epoch markets**

`active=true` filtra por mercados "destacados por Polymarket", no por todos los abiertos. Los epoch markets (UP/DOWN en 5min) no aparecen. Usar Gamma API con `closed=false` para discovery correcto.

---

**L-02 — `get_order_book()` necesita `token_id`, no `condition_id`** `[GOTCHA #2]`

- `condition_id` = ID del mercado completo
- `token_id` = ID del token específico (YES o NO)

Fuente del `token_id`: campo `clobTokenIds` de Gamma API (con `json.loads`). Pasando `condition_id` a `get_order_book()` da error o datos vacíos.

---

**L-03 — `clobTokenIds` es un string JSON, no un array** `[GOTCHA #1]`

Aunque luce como lista JSON, Gamma API lo devuelve como string. SIEMPRE:
```python
token_ids = json.loads(raw) if isinstance(raw, str) else raw
```

---

**L-04 — TTL de epoch markets ≈ 24h — la señal está en los últimos segundos** `[GOTCHA #6]`

El mercado se abre 24h antes de que resuelva. La vela de 5min que determina el resultado ocurre al final. La ventana de entrada útil son los últimos 45-90s para mean reversion y 300-600s para trend following.

---

**L-05 — Discovery con single-query pierde mercados near-expiry** `[GOTCHA #4]`

Una query ordenada por `startDate desc` devuelve solo mercados recién abiertos (TTL ~24h). Con rediscovery horario, se reemplazan antes de que lleguen a la ventana de entrada. Solución: dual-query merged (`startDate desc` + `endDate asc`).

---

**L-06 — Solo token YES tiene liquidez real** `[GOTCHA #3]`

El token NO (DOWN) raramente tiene bids/asks. Para señales bajistas, consultar siempre el token YES e invertir la lógica del umbral de probabilidad.

---

**L-07 — `midpoint None` causa `TypeError` silencioso** `[GOTCHA #5]`

Cuando el orderbook está vacío, `midpoint` existe en el dict pero con valor `None`. `dict.get("midpoint", 0)` devuelve `None` (no `0`). Siempre verificar explícitamente:
```python
mid = quote.get("midpoint")
if mid is None:
    return None
```

---

**L-08 — `OrderBookSummary` es un objeto Python, no un dict**

`client.get_order_book()` devuelve un objeto `OrderBookSummary`, no un dict. Acceso por atributo: `book.bids[0].price` (string), no `book["bids"][0]["price"]`. Los campos `.price` y `.size` son strings — hacer `float()` antes de operar.

---

**L-09 — `get_trades()` requiere objeto `TradeParams`, no kwargs**

```python
# MAL:
client.get_trades(market=condition_id)

# BIEN:
from py_clob_client.clob_types import TradeParams
client.get_trades(TradeParams(market=condition_id))
```

---

**L-10 — Rate limit: 60 req/10s — sin delay crashea con 429**

Con muchos mercados en paralelo se alcanza fácilmente. Añadir `asyncio.sleep(0.2)` entre requests y backoff exponencial en excepciones.

---

**L-11 — `endDate` viene como string ISO 8601 con `Z`, no como timestamp**

```python
datetime.fromisoformat(end_raw.replace("Z", "+00:00")).timestamp()
```

No usar `dateutil.parser` en producción — tiene dependencias extra innecesarias.

---

**L-12 — Mercados con `conditionId` None o `clobTokenIds` vacíos — defensividad obligatoria**

Algunos mercados en beta tienen campos incompletos. Siempre verificar:
```python
if not m.get("conditionId"): continue
if not token_ids: continue
```

---

**L-13 — Indicadores devuelven `None` si hay pocas velas**

ADX, Keltner, SuperTrend devuelven `None` si no hay suficientes candles para calcular. Siempre verificar:
```python
if adx_val is None:
    return None
```

---

**L-14 — Parámetros con nombre incorrecto causan fallos silenciosos**

`KeltnerChannel(atr_multiplier=2.0)` falla silenciosamente. El parámetro correcto es `multiplier=`. Revisar la firma exacta del constructor de cada indicador.

---

**L-15 — Acceder a `metadata` en lugar de `.value` en resultado de indicador**

`r.metadata.get("middle")` falla si la clave no existe en `metadata`. Usar `r.value` directamente — es el resultado principal del indicador.

---

**L-16 — Mercados long-duration sin filtro de TTL máximo contaminan el pipeline**

Mercados como "Will Bitmine hold BTC by 2027?" tienen TTL de meses. Si el sistema está diseñado para epoch markets de 24h, filtrar por TTL máximo.

---

**L-17 — `get_trades()` puede requerir auth (401/403) según el mercado**

Algunos mercados requieren autenticación para ver el historial de trades. Si se recibe 401/403, desactivar silenciosamente en lugar de crashear. Los orderbooks (`get_order_book`) siempre funcionan en modo público.

---

## 6. Falcon / Narrative MCP Server

| Campo | Valor |
|-------|-------|
| Tipo | Terceros (Prediction Market Intelligence) |
| Web | https://narrative.agent.heisenberg.so |
| MCP SSE URL | `https://narrative.agent.heisenberg.so/sse` |
| Auth | Bearer token (`FALCON_BEARER_TOKEN` en `.env`) |
| Protocolo | MCP sobre SSE — JSON-RPC 2.0 |

**Flujo de conexión:**

```
1. GET /sse  (con Authorization: Bearer <token>)
   → recibe evento SSE: event: endpoint / data: /messages/?session_id=<id>

2. POST /messages/?session_id=<id>  con body JSON-RPC:
   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
   → respuesta llega como evento SSE: event: message / data: {...}

3. POST /messages/?session_id=<id>
   {"jsonrpc":"2.0","method":"notifications/initialized"}

4. Llamadas a herramientas via tools/call o tools/list
```

**MCP Tools disponibles:**

| Tool | Descripción |
|------|------------|
| `authenticate` | Valida el token Bearer → devuelve user_id |
| `list_data_agents` | Lista agentes propios del usuario |
| `list_publicly_retrievable_agents` | Lista agentes públicos accesibles a todos |
| `perform_parameterized_retrieval` | Llama un agente con params → devuelve datos estructurados |

**Agentes públicos clave (para bots de trading):**

| ID | Nombre | Uso |
|----|--------|-----|
| **575** | Polymarket Market 360 | Whale concentration, volume trend, winning side, squeeze risk — análisis profundo de mercado |
| **596** | Polymarket Price Jumps | Saltos candle-to-candle por encima de umbral en un mercado específico |
| **556** | Polymarket Trades | Trades individuales filtrados por mercado, wallet, tiempo y lado |
| **568** | Polymarket Candlesticks | OHLC histórico por token_id |
| **574** | Polymarket Markets | Search/filter de mercados — punto de entrada para discovery |
| **581** | Wallet 360 | 60+ métricas de perfil de wallet (PnL, riesgo, comportamiento) |
| **584** | Heisenberg Leaderboard | Ranking H-Score de wallets — identifica smart money |
| **585** | Social Pulse | Posts trending en redes sociales por keywords — sentimiento |
| **579** | Polymarket Leaderboard | Ranking por PnL en un periodo de tiempo |
| **569** | Polymarket PnL | PnL realizado de una wallet en un rango |

**Parámetros de agentes clave:**

```
Agent 575 — Polymarket Market 360 (todos opcionales):
  condition_id          Hex condition ID del mercado o 'ALL'
  min_volume_24h        Volumen mínimo 24h en USD (ej. '50000')
  min_top1_wallet_pct   % mínimo de exposición del top wallet, 0-100 (ej. '30')
  volume_trend          'Spiking' | 'Normal' | 'Declining' | 'Dying Interest' | 'No Trades' | 'ALL'
  min_liquidity_percentile Percentil mínimo de liquidez 0-100 (ej. '70')
  max_unique_traders_7d Max traders únicos en 7d (ej. '10' para mercados thin)

  Devuelve: condition_id, question, slug, end_date, market_active,
            current_volume_24h, current_volume_7d, liquidity_percentile, liquidity_tier,
            liquidity_risk_flag, volume_trend, volume_collapse_risk_flag,
            top1_wallet_pct, top3_wallet_pct, top10_wallet_pct, whale_control_flag,
            unique_traders_7d, trades_per_hour_avg, peak_hour_trades,
            squeeze_risk_flag, yes_avg_pnl, no_avg_pnl, winning_side, net_pnl

Agent 556 — Polymarket Trades (todos opcionales, default=ALL):
  condition_id    Hex condition ID o 'ALL'
  proxy_wallet    Wallet address o 'ALL'
  side            'BUY' | 'SELL' | 'ALL'
  start_time      Unix timestamp inicio
  end_time        Unix timestamp fin (usar '2200000000' para "hasta ahora")

  Devuelve: condition_id, outcome, price, proxy_wallet, side, size, slug,
            timestamp, token_id, transaction_hash
```

**⚠️ GOTCHA — Conexiones concurrentes:** El servidor limita a 1 conexión SSE activa por token. Reutilizar la sesión entre llamadas en lugar de crear una nueva por cada llamada.

**Cliente Python (en producción en `src/data/falcon_client.py`):**

```python
from src.data.falcon_client import (
    fetch_herding_candidates,  # Agent 575 — devuelve {uuid: {top1_wallet_pct, direction, ...}}
    fetch_whale_trades,         # Agent 556 — devuelve [trade_dicts]
    fetch_market_360,           # Agent 575 por condition_id específico
)

# Herding: mercados donde un whale controla >30% del volumen
herding = fetch_herding_candidates(min_top1_wallet_pct=30.0, min_volume_24h=10_000)
# → {market_uuid: {top1_wallet_pct, direction, volume_trend, winning_side, squeeze_risk, ...}}

# Trades recientes de whales
trades = fetch_whale_trades(lookback_seconds=3600, min_size_usd=500.0)
# → [{condition_id, side, outcome, price, size, slug, timestamp, proxy_wallet, ...}]

# Análisis profundo de un mercado específico
market = fetch_market_360("0xabc123...")
# → {whale_control_flag, top1_wallet_pct, volume_trend, squeeze_risk_flag, ...}
```

---

## 7. Herramientas Complementarias

### Polymarket CLI (oficial)

| Campo | Valor |
|-------|-------|
| Repo | https://github.com/Polymarket/polymarket-cli |
| Lenguaje | Rust |
| Estado | Disponible — no integrado por defecto |
| Config | `~/.config/polymarket/config.json` |
| Env var | `POLYMARKET_PRIVATE_KEY` |

**Instalación:**

```bash
# Linux
curl -sSL https://raw.githubusercontent.com/Polymarket/polymarket-cli/main/install.sh | sh

# macOS
brew tap Polymarket/polymarket-cli https://github.com/Polymarket/polymarket-cli
brew install polymarket

# Desde fuente (cualquier plataforma con Rust)
git clone https://github.com/Polymarket/polymarket-cli && cd polymarket-cli
cargo install --path .
```

**JSON output**: cualquier comando acepta `--output json` / `-o json` para integración con scripts.

**Capacidades:**
- Browse y filtrar mercados desde terminal
- Órdenes: limit, market, batch, cancelar
- Ver posiciones, balances, historial
- CTF split/merge/redeem — canjear posiciones ganadoras a USDC
- Gestión de approvals ERC-20 y ERC-1155
- Wallets: crear, importar (EOA / Proxy relayer / Gnosis Safe)

**Cuándo integrar**: cuando se active trading real (`DRY_RUN=false`). El CLI tiene resuelto el flujo completo de signing + approvals + redemption. Antes de re-implementar el signing onchain en Python, evaluar usar el CLI con `-o json` como capa de ejecución intermedia.
