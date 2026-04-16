# Specialist Edge — Estrategia Completa de Copytrading en Polymarket

> Documento maestro consolidado. Recoge la tesis completa de la estrategia
> basada en detección de especialistas por universo de mercado, compound diario
> y routing híbrido con base de datos de rankings.
>
> Kaizen Trading System — v1.0 — Abril 2026

---

## ÍNDICE

1. [Concepto central y tesis](#1-concepto-central-y-tesis)
2. [Los 3 universos de mercado seleccionados](#2-los-3-universos-de-mercado-seleccionados)
3. [Definición operativa de "especialista"](#3-definición-operativa-de-especialista)
4. [Pipeline de detección de especialistas](#4-pipeline-de-detección-de-especialistas)
5. [Base de datos de rankings (200 perfiles × universo)](#5-base-de-datos-de-rankings)
6. [Contexto de operación por tipo de mercado](#6-contexto-de-operación-por-tipo-de-mercado)
7. [Routing híbrido: BD primero, scan como fallback](#7-routing-híbrido)
8. [Resolución de conflictos: especialistas en ambos lados](#8-resolución-de-conflictos)
9. [Flujo completo del bot (event-driven)](#9-flujo-completo-del-bot)
10. [Gestión de riesgo y trailing stop](#10-gestión-de-riesgo-y-trailing-stop)
11. [Mecánica de compound diario](#11-mecánica-de-compound-diario)
12. [Configuración completa](#12-configuración-completa)
13. [Estructura de archivos y orden de implementación](#13-estructura-de-archivos)

---

## 1. CONCEPTO CENTRAL Y TESIS

### El planteamiento original

La estrategia nace de una lógica event-driven: el bot se activa cada vez que necesita abrir un nuevo trade (al liberarse un slot) y arranca un buscador de la mejor opción disponible. El flujo operativo es:

1. Trabajar con 3 universos de mercado que se ajusten a la estrategia
2. Buscar eventos que se resuelvan en las próximas 24h (compound diario)
3. Seleccionar mercados favorables para análisis de especialistas
4. Analizar ambos lados del mercado buscando concentración de especialistas
5. Priorizar el lado más rentable (ROI mayor) pero respaldado por consenso
6. Posicionarse en la mejor opción disponible cuando haya slot libre
7. Diversificar con un máximo de trades abiertos por mercado/universo

### La pregunta fundamental que responde la estrategia

**No es "¿quién ha ganado más dinero?" sino "¿quién acierta más en ESTE tipo de mercado?"**

Un wallet con $2K de P&L total pero que ha acertado 8 de 10 mercados de "BTC Daily Above/Below" es infinitamente más valioso que un whale con $500K de P&L que solo acierta el 52% en esa categoría porque su beneficio viene de política o elecciones.

### Principios fundamentales

- **Especialización sobre generalización:** Un trader con alto hit rate en un nicho concreto predice mejor ese nicho que cualquier whale generalista.
- **Aciertos sobre dinero:** El posicionamiento se basa en número de aciertos en el universo específico, no en volumen ni en P&L absoluto.
- **Compound diario sobre grandes trades:** Múltiples trades pequeños que resuelven cada día, reinvirtiendo el equity disponible.
- **Event-driven sobre periódico:** El bot no escanea cada N horas; se activa cuando libera capital (trade cerrado o resuelto).
- **Base de datos evolutiva:** El conocimiento del sistema mejora con el tiempo — cuanto más opera, mejor identifica especialistas.

---

## 2. LOS 3 UNIVERSOS DE MERCADO SELECCIONADOS

Para encajar con compound diario necesitamos mercados que cumplan 5 condiciones:

1. Resuelven en ≤24 horas
2. Volumen suficiente para evitar slippage (≥$50K 24h)
3. Se generan nuevos mercados cada día
4. Existe diferenciación real entre traders (no es 50/50 aleatorio)
5. Los especialistas existen y se pueden detectar estadísticamente

### Universos elegidos y asignación de capital

```
┌────────────────────────────────┬──────────┬──────────┬──────────────┐
│ Universo                        │ Capital  │ Slots max│ Tipos cubre  │
├────────────────────────────────┼──────────┼──────────┼──────────────┤
│ Crypto Daily Above/Below        │   40%    │    3     │ crypto_above │
│   "BTC above $75K"              │          │          │ crypto_below │
│   "ETH above $2,400"            │          │          │              │
├────────────────────────────────┼──────────┼──────────┼──────────────┤
│ Crypto Daily Price Range        │   30%    │    2     │ price_range  │
│   "BTC price range 74K-76K"     │          │          │              │
├────────────────────────────────┼──────────┼──────────┼──────────────┤
│ Sports Game Winners             │   30%    │    2     │ sports_winner│
│   "Lakers vs Celtics"           │          │          │              │
│   NBA / NHL / MLB / NFL         │          │          │              │
└────────────────────────────────┴──────────┴──────────┴──────────────┘
TOTAL: 7 posiciones simultáneas máximo
```

### Nota sobre riesgo correlacionado

Los dos universos crypto comparten asset class. Si BTC cae 10% en una hora, ambos mercados pueden fulminarse simultáneamente. Durante el paper trading se medirá la correlación real de P&L entre ambos universos crypto. Si se confirma que eventos de volatilidad destruyen posiciones en paralelo:

- **Plan A (manteniendo los 2 crypto):** reforzar gestión de riesgo con trailing stops más conservadores
- **Plan B (si no es suficiente):** reducir a 1 solo universo crypto (el de mejor expected ROI histórico) y sustituir el segundo por política (resolución variable pero hay mercados de ≤24h en torno a votos legislativos) o ampliar sports a más ligas

La decisión se toma con datos reales de paper trading, no a priori.

---

## 3. DEFINICIÓN OPERATIVA DE "ESPECIALISTA"

### Qué NO es un especialista

- Un wallet con mucho dinero invertido
- Un wallet con alto P&L total
- Un wallet con win rate general alto (puede venir de otro universo)
- Un whale famoso que opera todo

### Qué SÍ es un especialista

Un wallet que cumple **todas** estas condiciones para un universo concreto:

```python
@dataclass
class SpecialistProfile:
    address: str
    universe: str

    # Métrica PRINCIPAL: hit rate en ESTE universo
    universe_trades: int          # Mercados resueltos en el universo
    universe_wins: int
    universe_hit_rate: float      # wins / trades EN ESTE UNIVERSO

    # Métricas de filtro
    universe_streak: int          # Racha actual
    last_active_ts: int
    avg_position_usd: float
    is_bot: bool

    # Score compuesto
    specialist_score: float

    # Contexto de operación (ver §6)
    top_types_by_hitrate: list[MarketTypeActivity]
    top_types_by_activity: list[MarketTypeActivity]
    all_type_activity: dict[str, MarketTypeActivity]
```

### Fórmula del specialist_score

```python
def calculate_specialist_score(sp: SpecialistProfile) -> float:
    """
    PESOS:
    - 50% hit rate en el universo (la métrica reina)
    - 20% volumen de muestra (más trades = más confianza)
    - 15% recencia (activo recientemente = relevante)
    - 15% consistencia (no un spike de suerte)
    """
    # Hit rate normalizado: 50% = 0, 80% = 1
    hr_score = min(max((sp.universe_hit_rate - 0.50) / 0.30, 0), 1.0)

    # Volumen: 10 trades = 0.3, 30+ trades = 1.0
    vol_score = min(sp.universe_trades / 30, 1.0)

    # Recencia: activo <7 días = ~1.0, >30 días = 0
    days_since_active = (time.time() - sp.last_active_ts) / 86400
    rec_score = max(0, 1.0 - days_since_active / 30)

    # Consistencia: racha positiva actual
    con_score = min(max(sp.universe_streak, 0) / 5, 1.0)

    return (
        hr_score * 0.50 +
        vol_score * 0.20 +
        rec_score * 0.15 +
        con_score * 0.15
    )
```

### Umbrales mínimos

```python
SPEC_MIN_UNIVERSE_TRADES = 10    # Mínimo 10 trades resueltos
SPEC_MIN_HIT_RATE = 0.58         # ≥58% de acierto
SPEC_MIN_SCORE = 0.35            # Score compuesto
SPEC_MAX_INACTIVE_DAYS = 14      # Activo en últimas 2 semanas
SPEC_NOT_BOT = True              # Pasa bot detection
```

---

## 4. PIPELINE DE DETECCIÓN DE ESPECIALISTAS

Para un wallet dado y un universo target, el sistema ejecuta 7 pasos:

### Paso 1 — Obtener historial de trades

```
Data API: GET /activity?user={wallet}&type=TRADE&limit=500
Paginar si hay más de 500 hasta cubrir 120 días.
Coste: 1-3 requests
```

### Paso 2 — Clasificar cada trade por tipo estructural

Se clasifica cada trade en un tipo específico usando slug + title + eventSlug (ver §6 para la taxonomía completa). Coste: 0 requests, procesamiento local.

### Paso 3 — Filtro rápido por volumen en universo

```python
universe_trades_count = len(trades_in_target_universe)
if universe_trades_count < SPEC_MIN_UNIVERSE_TRADES:  # 10
    return None  # DESCARTAR — sin suficiente historial
```

Este filtro elimina al 70-80% de los wallets con solo 1 request gastado. Es el punto crítico de optimización.

### Paso 4 — Determinar posición neta por mercado

Se agrupan los trades del universo por `conditionId` y se calcula la posición neta (YES o NO). Coste: 0 requests.

### Paso 5 — Verificar resolución

```
Data API: GET /positions?user={wallet}&sortBy=CASHPNL

Para cada conditionId con posición cerrada:
  - cashPnl > 0 → WIN
  - cashPnl ≤ 0 → LOSS
  - Posición abierta → EXCLUIR (no cuenta para hit rate)

Coste: 1-3 requests
```

### Paso 6 — Calcular hit rate y métricas

Local. Se calcula: wins, losses, hit_rate, current_streak, last_active_ts, avg_position_usd.

### Paso 7 — Score, evaluación, contexto de tipos

Se construye el SpecialistProfile completo incluyendo el contexto de operación (§6), se calcula specialist_score, y se evalúa contra umbrales.

### Coste total por wallet evaluado

```
Requests totales: 2-6 por wallet
Tiempo: ~200ms de requests + ~5ms local

Para un mercado con 50 holders:
  ~10-15 pasan Paso 3 (evaluación completa: 40-60 requests)
  ~35-40 descartados en Paso 3 (solo trades: 70-80 requests)
  TOTAL: ~110-140 requests, ~4-5 segundos

Para 3 mercados candidatos: ~15 segundos sin BD
Con BD en régimen maduro: ~1-2 segundos (ver §7)
```

---

## 5. BASE DE DATOS DE RANKINGS

### Estructura

```sql
-- Ranking principal: 200 especialistas × universo
CREATE TABLE specialist_ranking (
    wallet TEXT, universe TEXT,
    hit_rate REAL, universe_trades INTEGER, universe_wins INTEGER,
    specialist_score REAL, current_streak INTEGER,
    last_active_ts INTEGER, avg_position_usd REAL,
    is_bot BOOLEAN, rank_position INTEGER,
    first_seen_ts INTEGER, last_updated_ts INTEGER,
    last_seen_in_market TEXT,
    PRIMARY KEY(wallet, universe)
);

-- Índice de mercados donde hemos visto a cada especialista
CREATE TABLE specialist_markets (
    wallet TEXT, universe TEXT, condition_id TEXT,
    side TEXT, timestamp INTEGER,
    PRIMARY KEY(wallet, condition_id)
);

-- Contexto de operación por tipo de mercado (ver §6)
CREATE TABLE specialist_type_activity (
    wallet TEXT, market_type TEXT,
    trades INTEGER, wins INTEGER, hit_rate REAL,
    avg_position_usd REAL, last_active_ts INTEGER,
    last_30d_trades INTEGER,
    PRIMARY KEY(wallet, market_type)
);

-- Ranking agregado por tipo de mercado (ver §6)
CREATE TABLE market_type_rankings (
    market_type TEXT PRIMARY KEY,
    n_specialists INTEGER, avg_hit_rate REAL, top_hit_rate REAL,
    total_trades INTEGER, priority_score REAL,
    last_updated_ts INTEGER
);
```

### Por qué 200 perfiles por universo

- 50 holders × 3 mercados escaneados = 150 wallets max por scan
- 200 cubre holgadamente el pool esperado con margen para rotación
- Total 600 registros (3 universos) — queries instantáneas
- Suficiente granularidad para tener diversidad sin perder calidad

### Mantenimiento del ranking

```python
def update_ranking(universe, new_specialist):
    """
    Cuando se detecta un nuevo especialista:
    1. Si el ranking del universo no está lleno → insertar
    2. Si está lleno: comparar score con el #200
       - Si new_score > worst_score → reemplazar
       - Si no → registrar intento (no re-evaluar pronto)
    3. Renumerar posiciones
    """
    # [Lógica detallada en documento de detección]

def refresh_stale_profiles(max_age_hours=24, batch_size=20):
    """
    Tarea de background (no en hot path):
    Refrescar perfiles no actualizados en X horas.
    Priorizar los de mayor rank_position (mejores).
    Si un perfil ya no califica → eliminarlo del ranking.
    """
```

---

## 6. CONTEXTO DE OPERACIÓN POR TIPO DE MERCADO

### Taxonomía de tipos estructurales

Agrupación por **estructura de apuesta**, no por asset. Un especialista en "BTC above" probablemente también en "ETH above" (misma habilidad: análisis técnico), pero no necesariamente en "BTC price range" (habilidad distinta: predicción de volatilidad contenida).

```python
MARKET_TYPES = {
    # Crypto directional
    "crypto_above":        "Mercados 'X above $Y'",
    "crypto_below":        "Mercados 'X below $Y'",
    "crypto_price_range":  "Rangos 'X between $Y-$Z'",
    "crypto_hit_price":    "'X will hit $Y by date'",
    "crypto_updown_short": "Up/Down 15min/1h/4h (ignorar - bots)",
    "crypto_updown_daily": "Up/Down daily",

    # Sports
    "sports_winner":       "Game winners (NBA/NHL/MLB/NFL)",
    "sports_spread":       "Spreads (team covers)",
    "sports_total":        "Totals / Over-Under",
    "sports_futures":      "Futures (champion, MVP)",

    # Politics
    "politics_election":   "Elecciones y primarias",
    "politics_legislative": "Votos legislativos",
    "politics_executive":  "Executive orders",
    "politics_polls":      "Resultados de encuestas",

    # Economics
    "econ_fed_rates":      "Fed rate decisions",
    "econ_data":           "CPI, GDP, unemployment",

    # Otros
    "weather": "...", "tech": "...", "culture": "...", "other": "...",
}
```

### Relación universo ↔ tipos

```
UNIVERSO OPERABLE          TIPOS QUE LO COMPONEN
────────────────────   →   ───────────────────────────
crypto_above_below     →   [crypto_above, crypto_below]
crypto_price_range     →   [crypto_price_range]
sports_game_winner     →   [sports_winner]
```

Un especialista puede tener actividad en tipos que no operamos (p.ej. fed_rates, politics) — esto sigue siendo información valiosa para el contexto.

### Qué se guarda por especialista

Para cada wallet clasificado como especialista, se guardan:

**Top 3 tipos por hit rate** (con mínimo 5 trades cada uno):
- El tipo donde MEJOR acierta
- Su hit rate específico en ese tipo
- Cuántos trades ha hecho ahí

**Top 3 tipos por actividad** (volumen):
- Donde más opera (aunque no sea su mejor hit rate)
- Trades recientes (últimos 30 días)

**Mapa completo** de todos los tipos donde opera.

### Ejemplo: contexto del wallet `0x7a3b...f482`

```
TOP 3 POR HIT RATE:
┌────────────────────────┬────────┬──────┬──────────┬──────────────┐
│ Market Type            │ Trades │ Wins │ Hit Rate │ Avg Size     │
├────────────────────────┼────────┼──────┼──────────┼──────────────┤
│ 1. crypto_above        │   30   │  19  │   63.3%  │    $720      │
│ 2. crypto_below        │   14   │   9  │   64.3%  │    $580      │
│ 3. econ_fed_rates      │    6   │   4  │   66.7%  │    $900      │
└────────────────────────┴────────┴──────┴──────────┴──────────────┘

INSIGHT: Es especialista en direccional crypto (above/below con 63-64%).
También bueno en Fed rates (muestra pequeña pero sólida).
Opera price-range pero NO es bueno ahí (50% = random).
Su mayor edge: crypto_below (64.3%).
```

### Ranking agregado por tipo de mercado

```python
def calculate_type_priority_score(type_stats):
    """
    PRIORIZACIÓN POR HIT RATE (decisión del usuario).

    Factores:
    - 50%: top_hit_rate (el mejor especialista del tipo)
    - 30%: avg_hit_rate (calidad media)
    - 10%: n_specialists (diversidad)
    - 10%: recencia
    """
    # Requisito: ≥3 especialistas para considerar el tipo
    # Normalización: top_hr 55%-80% → 0-1
    # Normalización: avg_hr 52%-68% → 0-1
    # Diversity: 3 = 0.3, 10+ = 1.0
    # Recency: últimos 14 días
```

Este ranking se recalcula cada 6h y determina qué tipos priorizar en el routing.

---

## 7. ROUTING HÍBRIDO

### Estrategia: BD primero, scan como fallback

Cuando se libera un slot, el sistema NO escanea ciegamente 20 mercados. Consulta primero la BD de rankings de tipos para decidir qué tipo priorizar, luego busca solo mercados de ese tipo, y cruza rápidamente con los especialistas conocidos.

### Flujo completo

```
TRIGGER: Slot libre en universo "crypto_above_below"

FASE A — CONSULTAR BD (1ms)
  ¿Qué tipo está mejor rankeado ahora?
    SELECT * FROM market_type_rankings
    WHERE market_type IN ('crypto_above', 'crypto_below')
    ORDER BY priority_score DESC;

  Resultado:
    crypto_below: priority_score 0.78 (top HR 71%, 8 specs)
    crypto_above: priority_score 0.64 (top HR 68%, 12 specs)
  → Priorizar crypto_below

FASE B — OBTENER WALLETS CONOCIDOS DEL TIPO (1ms)
  Query BD por los 8 wallets conocidos con hit rate ≥58% en crypto_below

FASE C — BUSCAR MERCADOS DEL TIPO ACTIVOS (≤24h) (1 req)
  Gamma API → mercados crypto_below que resuelven hoy
  Resultado: 4 mercados candidatos
    - BTC below $72K
    - ETH below $2.3K
    - SOL below $85
    - DOGE below $0.15

FASE D — CRUCE RÁPIDO (1 req por mercado)
  Para cada candidato, obtener holders y cruzar con los 8 conocidos:
    BTC below:  3/8 conocidos → BD ONLY (decisión instantánea)
    ETH below:  1/8 conocidos → HÍBRIDO (conocido + scan desconocidos)
    SOL below:  5/8 conocidos → BD ONLY
    DOGE below: 0/8 conocidos → SCAN COMPLETO (fallback)

FASE E — EVALUACIÓN DE SEÑAL
  Cada mercado evalúa consenso de especialistas usando:
    - hit rate DEL TIPO ESPECÍFICO (no universo global)
    - specialist_score ponderado por type_hit_rate

FASE F — COMPARAR MERCADOS Y ELEGIR MEJOR ROI
  Mercados evaluados:
    SOL below $85 YES   → Expected ROI 180%, CLEAN
    BTC below $72K YES  → Expected ROI 95%, CLEAN
    ETH below $2.3K NO  → Expected ROI 60%, CONTESTED
    DOGE below: SKIP (sin consenso tras scan)
  → EJECUTAR SOL below $85 YES

TIEMPO TOTAL: ~1-2 segundos (vs 15s sin BD)
```

### Reglas híbridas

```python
# Decisión por mercado según conocidos presentes:

if known_count >= 3 and all(hr >= 0.60 for hr in known_hrs) \
        and all(age < 12h for data):
    → USE_BD_ONLY           # 0 requests extra

elif known_count >= 1:
    → HYBRID                 # Conocidos + scan de desconocidos

else:  # known_count == 0
    → FULL_SCAN              # Fallback completo
```

### Anti-ceguera (discovery forzado)

```python
def ensure_discovery_coverage():
    """
    Si de los últimos 10 scans TODOS fueron BD pura,
    forzar 1 scan completo en un tipo sub-representado.

    Previene que el bot se encierre en los mismos tipos
    y pierda capacidad de descubrir especialistas emergentes.
    """
```

### Evolución temporal

```
Semana 1: BD vacía → mayoría fallback → descubrimos ~40 specs/día
Semana 2: BD con 200 perfiles → 60% cobertura
Semana 3: BD madura → 80% cobertura, contextos establecidos
Semana 4+: auto-evolutiva, nuevos entran, malos salen
           Rankings de tipos guían atención a los de mejor HR
```

---

## 8. RESOLUCIÓN DE CONFLICTOS

### El problema: especialistas en ambos lados

Mercado: "BTC above $76,000 today"

```
Especialistas YES:
  Wallet A: HR 68%, score 0.72
  Wallet B: HR 61%, score 0.48
  Wallet C: HR 59%, score 0.41
  TOTAL: 3 specs, score 1.61

Especialistas NO:
  Wallet D: HR 71%, score 0.78
  Wallet E: HR 63%, score 0.52
  TOTAL: 2 specs, score 1.30
```

### Clasificación de la señal

```python
ratio = dominant_score / max(opposite_score, 0.01)

# CLEAN (ratio ≥ 2.5 Y oposición ≤ 1 especialista):
#   Máxima confianza, sizing completo
#   Pequeña penalización si hay 1 opositor

# CONTESTED (ratio 1.5 - 2.5):
#   Penalización 15-30% de confianza
#   Sizing reducido
#   Solo operar si no hay CLEAN disponible

# SKIP (ratio < 1.5):
#   No operar. Mercado genuinamente dividido.
```

### Ejemplo aplicado al mercado BTC $76K

```
Score YES: 1.61, Score NO: 1.30
Ratio: 1.61 / 1.30 = 1.24
→ SKIP (< 1.5)
→ Los especialistas están divididos, no hay consenso claro
→ Buscar otro mercado
```

### Ejemplo contrario: señal CLEAN con penalización

```
Mercado: SOL above $90
Precio: $0.30 (YES)
Specs YES: 4, score 2.4
Specs NO: 1, score 0.5
Ratio: 4.8 → CLEAN (ratio ≥ 2.5 Y oposición ≤ 1)

Conflict penalty: 0.5 / 2.9 = 0.17
Confidence: min(2.4/3, 0.95) × (1 - 0.17 × 0.5) = 0.80 × 0.92 = 0.73

Potential ROI: (1.0 - 0.30) / 0.30 = 233%
Expected ROI: 233% × 0.73 = 170%

→ SEÑAL MUY FUERTE
→ Sin oposición hubiera sido 186% (diferencia solo -8.6%)
→ La oposición reduce ROI proporcional y razonablemente
```

### Priorización entre mercados candidatos

```python
def compare_market_candidates(candidates):
    """
    1. signal_quality == "clean" SIEMPRE gana sobre "contested"
    2. Dentro de misma calidad, mayor expected_roi gana
    3. En empate de ROI, más especialistas gana
    4. Segundo desempate: menos oposición
    """
    clean = [c for c in candidates if c["quality"] == "clean"]
    pool = clean if clean else [c for c in candidates if c["quality"] == "contested"]
    return max(pool, key=lambda c: (
        c["expected_roi"],
        c["n_dominant"],
        -c["n_opposite"],
    ))
```

---

## 9. FLUJO COMPLETO DEL BOT

```
═══════════════════════════════════════════════════════════
  TRIGGER: Un slot se libera (trade cerrado/resuelto)
           o primera ejecución del día
═══════════════════════════════════════════════════════════

FASE 1: ¿QUÉ UNIVERSO NECESITA TRADE?
  1.1  Contar posiciones abiertas por universo
  1.2  Comparar con MAX_SLOTS
  1.3  Si ninguno tiene slot libre → ESPERAR
  1.4  Si múltiples → priorizar:
       a) Más capital asignado sin usar
       b) Mercados resolviendo más pronto

FASE 2: ROUTING (BD PRIMERO)
  Ver §7 para flujo detallado.
  Consultar market_type_rankings para priorizar tipo.
  Obtener wallets conocidos del tipo.
  Buscar mercados del tipo activos ≤24h.

FASE 3: CRUCE Y ANÁLISIS POR MERCADO
  Para cada candidato:
    - Cruzar holders con BD
    - Si ≥3 conocidos con datos frescos → BD only
    - Si 1-2 → híbrido
    - Si 0 → scan completo (fallback)

FASE 4: EVALUACIÓN DE SEÑAL
  Para cada mercado con análisis:
    - Calcular score_yes, score_no (ponderado por type_hit_rate)
    - Clasificar: CLEAN / CONTESTED / SKIP
    - Calcular expected_roi

FASE 5: SELECCIÓN Y EJECUCIÓN
  Comparar 2-5 mercados candidatos.
  Elegir mejor: clean > contested, luego mayor expected_roi.

  Ejecución:
    - Verificar order book (spread <5¢, depth ≥$5K)
    - Sizing: capital_universo × 40% del disponible × signal_score
    - LIMIT order al midpoint + 0.01
    - Retry hasta 120s, luego SKIP

FASE 6: GESTIÓN DE POSICIÓN
  Ver §10 para trailing stop detallado.
  Checks cada 15 minutos.
  Resolución del mercado → SLOT LIBERADO → trigger FASE 1.
```

---

## 10. GESTIÓN DE RIESGO Y TRAILING STOP

### Parámetros ajustados (más holgados)

```python
TS_ACTIVATION_PCT = 0.08    # Activar trailing al +8% unrealized
TS_TRAIL_PCT = 0.15         # 15% debajo del high water mark
HARD_STOP_LOSS_PCT = -0.20  # -20% desde entrada
```

### Lógica de trailing stop

```python
def manage_position(position, current_price):
    """
    El trailing stop se activa cuando el precio se mueve ≥8% a favor.
    Una vez activado, trail al 15% del high water mark.

    "No muy ceñido" = permite aire para volatilidad intradía sin
    cerrar prematuramente.
    """
    unrealized_pct = (current_price - position.entry_price) / position.entry_price
    # (invertir para posiciones NO)

    # Hard stop loss (antes de que se active trailing)
    if unrealized_pct <= HARD_STOP_LOSS_PCT:  # -20%
        close_position(position)
        return "HARD_STOP"

    # Activar trailing
    if unrealized_pct >= TS_ACTIVATION_PCT and not position.trailing_active:
        position.trailing_active = True
        position.high_water_mark = current_price

    # Actualizar trailing
    if position.trailing_active:
        if current_price > position.high_water_mark:
            position.high_water_mark = current_price

        trailing_price = position.high_water_mark * (1 - TS_TRAIL_PCT)
        if current_price <= trailing_price:
            close_position(position)
            return "TRAILING_STOP"

    # Salida por resolución (ideal)
    if market_resolved(position.market):
        settle_position(position)
        return "RESOLUTION"

    return "HOLD"
```

### Circuit breakers globales

```python
MAX_DRAWDOWN_PCT = 0.30        # 30% equity → detener TODO
DAILY_LOSS_LIMIT = 0.10        # 10% día → pausa 24h
MAX_OPEN_POSITIONS = 7         # Total simultáneas
MIN_LIQUIDITY_24H = 50_000     # Mínimo volumen del mercado
MAX_SPREAD_FOR_ENTRY = 0.05    # No entrar si spread > 5¢
```

---

## 11. MECÁNICA DE COMPOUND DIARIO

### Cómo se genera el compound

Con mercados que resuelven en ≤24h y múltiples posiciones simultáneas, el capital rota rápido:

```
Día ejemplo con $500 equity inicial:

08:00 UTC — Entry: BTC above $75K YES a $0.43, size $40
09:00 UTC — Entry: Celtics vs Lakers YES a $0.58, size $30
10:00 UTC — Entry: BTC price range 74K-76K YES a $0.36, size $30

23:30 UTC — Celtics ganan → +$21.7
00:00 UTC — BTC above resuelve YES → +$53.0
00:00 UTC — BTC range resuelve YES → +$53.3

Día 1: 3 trades, +$128 (+25.6%)
Día 2: Arranca con $628, sizing reinvierte automáticamente
```

### Sizing con compound

```python
def calculate_trade_size(universe, signal_score, equity):
    """
    El sizing escala con el equity actual (compound automático).
    """
    universe_capital = equity * UNIVERSE_ALLOCATION[universe]
    open_in_universe = sum(sizes of open positions in universe)
    available = universe_capital - open_in_universe

    base_size = available * 0.40  # Max 40% del libre por trade

    # Ajustar por signal_score
    trade_size = base_size * signal_score

    # Caps
    trade_size = min(trade_size, equity * 0.10)  # Max 10% equity
    trade_size = min(trade_size, 100)             # Max $100 absoluto
    trade_size = max(trade_size, 5)               # Min $5
```

### Por qué funciona el compound

1. **Resolución rápida** → capital liberado frecuentemente
2. **Profit binario** → cuando ganas, ganas MUCHO ($0.40 entry → $1.00 resolution = 150%)
3. **Sizing proporcional** → ganancias se reinvierten automáticamente
4. **Múltiples posiciones simultáneas** → diversificación temporal

### Control de riesgo del compound

- 8% del equity por trade → necesitas 12 losses consecutivos para -30% drawdown
- Max 7 posiciones simultáneas → no concentración extrema
- Trailing stop protege ganancias → no devuelve al 0%
- Hard stop -20% → limita pérdida individual

---

## 12. CONFIGURACIÓN COMPLETA

```python
# ═══ UNIVERSOS ═══════════════════════════════════════════
UNIVERSES = {
    "crypto_above_below": {
        "types": ["crypto_above", "crypto_below"],
        "allocation": 0.40,
        "max_slots": 3,
    },
    "crypto_price_range": {
        "types": ["crypto_price_range"],
        "allocation": 0.30,
        "max_slots": 2,
    },
    "sports_game_winner": {
        "types": ["sports_winner"],
        "allocation": 0.30,
        "max_slots": 2,
    },
}

# ═══ SPECIALIST DETECTION ════════════════════════════════
SPEC_MIN_UNIVERSE_TRADES = 10
SPEC_MIN_HIT_RATE = 0.58
SPEC_MIN_SCORE = 0.35
SPEC_MAX_INACTIVE_DAYS = 14
SPEC_CACHE_TTL_HOURS = 12

# ═══ RANKING DB ══════════════════════════════════════════
RANKING_SIZE_PER_UNIVERSE = 200
RANKING_REFRESH_STALE_HOURS = 24
RANKING_REFRESH_BATCH_SIZE = 20

# ═══ MARKET TYPE CONTEXT ═════════════════════════════════
TYPE_MIN_TRADES_FOR_HITRATE = 5
TYPE_TOP_N = 3
TYPE_RANKING_MIN_SPECIALISTS = 3
TYPE_RANKING_REFRESH_HOURS = 6
TYPE_PRIORITY_TOP_HR_WEIGHT = 0.50
TYPE_PRIORITY_AVG_HR_WEIGHT = 0.30
TYPE_PRIORITY_DIVERSITY_WEIGHT = 0.10
TYPE_PRIORITY_RECENCY_WEIGHT = 0.10

# ═══ HYBRID ROUTING ══════════════════════════════════════
HYBRID_BD_ONLY_MIN_KNOWN = 3
HYBRID_BD_ONLY_MIN_HR = 0.60
HYBRID_BD_ONLY_MAX_AGE_HOURS = 12
FORCE_DISCOVERY_SCAN_AFTER = 10

# ═══ SIGNAL QUALITY ══════════════════════════════════════
SIGNAL_MIN_DOMINANT_SPECIALISTS = 2
SIGNAL_MIN_RATIO_CLEAN = 2.5
SIGNAL_MIN_RATIO_CONTESTED = 1.5
SIGNAL_MAX_OPPOSITE_CLEAN = 1
SIGNAL_MIN_TOP_HIT_RATE = 0.65

# ═══ MARKET FILTERING ════════════════════════════════════
MARKET_MIN_VOLUME_24H = 50_000
MARKET_MAX_HOURS_TO_RESOLUTION = 24
MARKET_PRICE_MIN = 0.15
MARKET_PRICE_MAX = 0.75
MARKET_MAX_SPREAD = 0.05

# ═══ SIZING ══════════════════════════════════════════════
SIZING_BASE_PCT = 0.08
SIZING_MAX_PCT = 0.10
SIZING_MAX_USD = 100
SIZING_MIN_USD = 5

# ═══ TRAILING STOP (ajustado) ════════════════════════════
TS_ACTIVATION_PCT = 0.08
TS_TRAIL_PCT = 0.15
HARD_STOP_LOSS_PCT = -0.20

# ═══ CIRCUIT BREAKERS ════════════════════════════════════
MAX_DRAWDOWN_PCT = 0.30
DAILY_LOSS_LIMIT = 0.10
MAX_OPEN_POSITIONS = 7

# ═══ EXECUTION ═══════════════════════════════════════════
ORDER_TYPE = "LIMIT"
LIMIT_OFFSET = 0.01
ORDER_TIMEOUT_SECONDS = 120
POSITION_CHECK_INTERVAL_MINUTES = 15
```

---

## 13. ESTRUCTURA DE ARCHIVOS

```
polymarket-copytrade/
├── common/                          # REUTILIZADO de implementación existente
│   ├── config.py                    # Constantes (ver §12)
│   ├── gamma_client.py              # Gamma API
│   ├── data_client.py               # Data API
│   ├── clob_client.py               # CLOB API
│   ├── bot_detector.py              # Detección de bots
│   └── risk_manager.py              # Circuit breakers
│
├── strategy_specialist/
│   ├── universe_config.py           # Definición universos y tipos
│   ├── market_type_classifier.py    # Taxonomía §6
│   ├── specialist_profiler.py       # Pipeline §4 (detección)
│   ├── type_context_builder.py      # Contexto §6 (top 3 tipos)
│   ├── ranking_db.py                # BD rankings §5
│   ├── market_type_rankings.py      # Rankings agregados por tipo §6
│   ├── hybrid_router.py             # Routing §7 (BD primero)
│   ├── market_scanner.py            # Buscar mercados del tipo
│   ├── specialist_analyzer.py       # Análisis de holders por mercado
│   ├── signal_generator.py          # Señales §8 (clean/contested/skip)
│   ├── trade_executor.py            # Sizing + ejecución
│   ├── position_manager.py          # Trailing stop §10
│   └── slot_orchestrator.py         # Flujo event-driven §9
│
├── background_tasks/
│   ├── refresh_stale_profiles.py    # Refrescar perfiles cada 24h
│   ├── update_type_rankings.py      # Recalcular ranking tipos cada 6h
│   └── force_discovery.py           # Anti-ceguera (cada 10 scans)
│
├── monitoring/
│   ├── compound_tracker.py          # Dashboard equity
│   ├── pnl_tracker.py
│   └── alerter.py
│
├── main.py                          # Entry point event-driven
└── .env
```

### Orden de implementación

**Sprint 1 — Foundation (módulos comunes, ya existentes)**
- `config.py`, `gamma_client.py`, `data_client.py`, `bot_detector.py`, `risk_manager.py`

**Sprint 2 — Specialist Detection**
- `universe_config.py`, `market_type_classifier.py`, `specialist_profiler.py`, `type_context_builder.py`
- **TEST:** Para 10 wallets conocidos, verificar que el hit rate por universo se calcula correctamente

**Sprint 3 — Database**
- `ranking_db.py`, `market_type_rankings.py`
- Poblar inicialmente con 5-10 mercados manuales
- **TEST:** Verificar que inserción/actualización/rotación funciona

**Sprint 4 — Routing + Signals**
- `hybrid_router.py`, `market_scanner.py`, `specialist_analyzer.py`, `signal_generator.py`
- **TEST:** 1 semana de señales sin ejecución (paper). Validar tasa de acierto esperada

**Sprint 5 — Execution**
- `position_manager.py`, `trade_executor.py`, `slot_orchestrator.py`
- **TEST:** Primeros trades reales con $5 para validar pipeline completa

**Sprint 6 — Background tasks + monitoring**
- `refresh_stale_profiles.py`, `update_type_rankings.py`, `force_discovery.py`
- Dashboard de compound, alertas

**Sprint 7 — Escalado**
- Empezar con $500-1000
- Si paper trading confirma correlación crypto → considerar sustituir 1 universo
- Ajustar parámetros basándose en datos reales

---

*Kaizen Trading System — Specialist Edge Strategy v1.0 — Abril 2026*
