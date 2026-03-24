# Polymarket Contrarian Bot — Project Context

> Actualizado: 2026-03-24 18:35 UTC
> Actualizado cada 12h por run_collector.py. Editar manualmente para notas permanentes.

---

## Estado de fases

| Fase | Estado | Descripcion |
|------|--------|-------------|
| Fase 1: Data Collection | **COMPLETA** | Collector corriendo, snapshots acumulando |
| Fase 2: Signal Engine | **COMPLETA** | Engine generando senales con filtros limpios + whale data v2 |
| Fase 3: Paper Trading | **EN CURSO** | Reset limpio 2026-03-22. 2 trades abiertos |
| Fase 4: Dashboard | Pendiente | Next.js en Vercel |
| Fase 5: Optimizacion | Pendiente | Ajustar thresholds con datos reales |

---

## Arranque rapido

```powershell
python scripts/run_collector.py       # Terminal 1
python scripts/run_signal_engine.py   # Terminal 2
python scripts/run_paper_trader.py    # Terminal 3
```

Verificar en log: `(filtered 795 sports)` confirma filtros activos.
Los procesos se caen al cerrar VS Code — normal en desarrollo local. En produccion (VPS) correran 24/7.

---

## Stats actuales (2026-03-24 18:31 UTC — auto)

| Metrica | Valor |
|---------|-------|
| Snapshots en DB | 404,547 |
| Ultimo snapshot | 2026-03-24T18:28 UTC |
| Mercados totales | 4,388 |
| Wallets watched | 29 |
| Senales generadas | 22 totales (0 activas — expiradas) |
| Trades abiertos | 2 ($97.50 en posiciones) |
| Trades cerrados | 0 (post-reset limpio) |
| P&L realizado | $0.00 |
| Capital actual | $902.50 (inicio: $1,000) |
| Win rate | 0% (sin trades cerrados aun) |
| Circuit breaker | OK |

**Trades abiertos (post-reset, limpios):**
- YES @ $0.060 — abierto 2026-03-23T08:58
- NO @ $0.589 — abierto 2026-03-23T19:25

---

## Arquitectura de archivos

```
src/
  data/
    polymarket_client.py      # CLOB + Gamma API wrapper
    polymarketscan_client.py  # PolymarketScan API (rate limit 28 req/min)
    market_scanner.py         # Escanea y filtra mercados candidatos
    snapshot_collector.py     # Precio + orderbook cada 2 min
    whale_trades_collector.py # Whale trades — migrando a Agent API
    falcon_client.py          # [EN PROGRESO] Falcon herding + whale trades
    leaderboard_seeder.py     # Top traders -> watched_wallets

  signals/
    divergence_detector.py    # Herding + velocidad de precio
    momentum_filter.py        # Score de momentum (0-100)
    contrarian_logic.py       # Smart wallet score + decision de senal
    signal_engine.py          # Combina todo -> DB signals

  trading/
    risk_manager.py           # Kelly sizing, circuit breaker, drawdown
    paper_trader.py           # open_trade / close_trade con P&L
    position_manager.py       # Trailing stop, take profit, timeout
    portfolio_tracker.py      # Stats y resumen del portfolio

  utils/
    config.py                 # Todos los parametros de estrategia
    context_updater.py        # Actualiza CONTEXT.md cada 12h
    logger.py                 # Loguru logger

scripts/
  run_collector.py            # Entry point Fase 1
  run_signal_engine.py        # Entry point Fase 2
  run_paper_trader.py         # Entry point Fase 3
  run_cleanup.py              # Limpieza diaria
  setup_db.py                 # Verificar conexion y schema
```

---

## Decisiones de diseno

### APIs
- **Polymarket Gamma API** — fuente principal de mercados
- **Polymarket CLOB API** — precios en tiempo real (404 en AMM-only es normal, en DEBUG)
- **PolymarketScan Public API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api` (28 req/min)
- **PolymarketScan Agent API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api` (60 req/min, sin auth). Accion `?action=whales&limit=50&agent_id=contrarian-bot` reemplaza endpoint whale_trades del Public API que devuelvia []
- **Falcon API** — `https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized` POST. Misma URL base que MCP server. Bearer token en .env. Agent IDs: 575 (Market Insights/herding), 556 (Whale Trades)

### Integracion whale data (COMPLETA — 2026-03-24)

Prioridad de fuentes para deteccion de herding (implementada en detect_whale_herding_v2):
1. **Falcon Market Insights** (agent_id=575) — herding por concentracion de wallets. Si top1_wallet_pct > 30% → candidato contrarian fuerte. **ESTADO: endpoint /parameterized devuelve 400 por error server-side (pipeline falla en campo timestamp/category). Implementado con fallback gracioso — retorna vacio. Arquitectura lista para re-activar cuando Falcon lo corrija.**
2. **PMS Agent API** (action=whales) — **ACTIVO Y FUNCIONANDO**. 50 trades, ~21 mercados por llamada. Cada ciclo del signal engine llama a esta API fresca (no se guarda en snapshots).
3. **Snapshot-based herding** (detect_whale_herding) — lee whale_direction de DB. Fallback si mercado no aparece en PMS.
4. **Momentum de precio** (>5% en 1h) — ultimo fallback cuando sample_size == 0

Archivos modificados (2026-03-24):
- `src/data/falcon_client.py` — CREADO. fetch_herding_candidates() + fetch_whale_trades() con graceful degradation
- `src/data/whale_trades_collector.py` — migrado de Public API (devolvia []) a Agent API (?action=whales)
- `src/signals/divergence_detector.py` — detect_whale_herding_v2() con prioridad Falcon > PMS > snapshots > momentum
- `src/signals/signal_engine.py` — llama Falcon + PMS al inicio de cada ciclo, pasa a detect_whale_herding_v2
- `src/utils/config.py` — POLYMARKETSCAN_AGENT_API_URL, FALCON_API_URL, FALCON_BEARER_TOKEN
- `.env` — FALCON_BEARER_TOKEN anadido (mismo JWT del MCP server)

### Estrategia
- **Divergencia proxy v1:** whale herding + velocidad de precio > 5% en 1h
- **Fallback sin whale data:** velocidad-only >= 5%/1h, divergence_score = vel_norm * 100
- **Seleccion de mercados:** top 500 por score compuesto = vol*0.3 + proximidad*0.4 + velocidad*0.3 (min vol $1k)
- **Pesos del score:** divergencia 50%, momentum 30%, smart wallet 20%
- **Threshold de senal:** 65/100
- **Categorias excluidas:** sports (filtro por keywords en pregunta, no por campo category que llega vacio)
- **Ventana de mercados:** 6h a 7d hasta resolucion

### Risk management
- Half-Kelly sizing (Kelly x 0.5), max 5% capital por trade
- Max 5 posiciones abiertas simultaneas
- Circuit breaker: 3 perdidas consecutivas → pausa 24h
- Max drawdown: 20% → pausa
- Trailing stop: 25% | Take profit: 50%

### Paper trader: precio de entrada (CRITICO para backtesting)
- `open_trade()` usa `price_at_signal`, NO el precio actual del mercado
- **Por que:** en produccion el trader ejecuta segundos despues de la senal. En desarrollo local el PC esta apagado a ratos y el gap puede ser horas — precio actual seria incorrecto
- **Riesgo si se revierte:** precios de ejecucion irreales sesgarian toda la evaluacion
- `_get_current_price()` sigue usandose en `position_manager.py` para trailing stop/TP (correcto)

### Filtros de calidad de senales
- Sports: 795 mercados eliminados por keywords en pregunta (category='' de la API es poco fiable)
- Precio minimo MIN_ENTRY_PRICE=0.05. Aplica en ambas direcciones:
  - YES signal: yes_price < 0.05 → skip (entrada sub-penny)
  - YES signal: yes_price > 0.95 → skip (mercado casi resuelto YES, sin edge)
  - NO signal: yes_price < 0.05 → skip (mercado casi resuelto NO, sin edge)
  - NO signal: 1 - yes_price < 0.05 → skip (entrada sub-penny)

### Datos
- `clobTokenIds` puede llegar como JSON string o lista Python — normalizer maneja ambos
- Mercados con token IDs < 10 chars se consideran corruptos y se nullean
- Snapshots sin precio (CLOB 404) se descartan
- Windows CP1252 no soporta emojis — logs usan ASCII puro

---

## Historial de bugs resueltos

| Bug | Estado | Descripcion |
|-----|--------|-------------|
| whale_trades Public API devuelve [] | **Resuelto (2026-03-24)** | Migrado a Agent API (?action=whales). 50 trades/llamada funcionando |
| Falcon parameterized endpoint devuelve 400 | Bloqueado (server-side) | Pipeline de Falcon falla internamente. Implementado con graceful fallback. PMS Agent API es la fuente primaria activa |
| Filtro sports no funcionaba | Resuelto (2026-03-22) | Gamma devuelve category=''. Filtro por keywords |
| Mercados sub-$0.05 generaban senales | Resuelto (2026-03-22) | MIN_ENTRY_PRICE=0.05 |
| Senales en mercados casi resueltos | Resuelto (2026-03-23) | Filtro yes_price > 0.95 / < 0.05 |
| position_manager: RESOLUTION clasificada como TRAILING_STOP | Resuelto (2026-03-22) | _is_resolved() detecta ambas direcciones |
| Paper trader usaba precio actual en vez de price_at_signal | Resuelto (2026-03-22) | open_trade() usa price_at_signal |
| 10 trades contaminados (deportivos + sub-penny) | Resuelto (2026-03-22) | CANCELLED, portfolio reseteado a $1,000 |
| CLOB 404 masivos | Resuelto (silenciado) | Mercados AMM-only, en DEBUG |
| Leaderboard solo 29 wallets | Limitacion API | PolymarketScan retorna 29 en lugar de 100 |
| get_active_markets_from_db sin paginacion | Pendiente | Fix: anadir paginacion |

---

## Parametros clave (config.py)

```python
DIVERGENCE_THRESHOLD_MIN    = 0.10
DIVERGENCE_THRESHOLD_STRONG = 0.15
MIN_VOLUME_24H              = 10_000   # market_scanner
MIN_LIQUIDITY               = 5_000
MIN_HOURS_TO_RESOLUTION     = 6
MAX_HOURS_TO_RESOLUTION     = 168
SIGNAL_THRESHOLD            = 65
INITIAL_CAPITAL             = 1000.0
MIN_ENTRY_PRICE             = 0.05
# signal_engine internos:
#   _MIN_VOLUME = 1_000
#   _CANDIDATE_TOP_N = 500
#   fallback velocity threshold = 0.05 (5%)
```

---

## Credenciales y entorno

- `.env` en raiz del proyecto (no commitear)
- Python 3.11+ requerido, venv en `.venv/`
- Supabase URL: `https://pdmmvhshorwfqseattvz.supabase.co`
- PolymarketScan Public API: `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api`
- PolymarketScan Agent API: `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api`
- Falcon/narrative API: `https://narrative.agent.heisenberg.so` — Bearer token en .env

---

## Proximo paso inmediato

**Whale data integration: COMPLETA** (2026-03-24)
- PMS Agent API activo como fuente primaria (50 trades/ciclo)
- Falcon en standby (error server-side, arquitectura lista)
- detect_whale_herding_v2 con prioridad Falcon > PMS > snapshots > momentum

**Fase 4 Dashboard (cuando):**
- [x] Al menos 1 senal generada
- [x] Al menos 1 trade abierto
- [ ] 48h de datos limpios (desde 2026-03-22 22:16 UTC)
- [ ] Al menos 1 trade limpio cerrado (post-reset)
