# Polymarket Contrarian Bot — Project Context

> Actualizado: 2026-03-29 19:30 UTC
> Actualizado manualmente tras cada sesion de trabajo. Editar manualmente para notas permanentes.

---

## Estado de fases

| Fase | Estado | Descripcion |
|------|--------|-------------|
| Fase 1: Data Collection | **COMPLETA** | Collector corriendo 24/7 en VPS |
| Fase 2: Signal Engine | **COMPLETA** | Engine con whale data v2 (PMS Agent API activo) |
| Fase 3: Paper Trading | **EN CURSO** | Run 2: 16 closed (12W 4L) + 1 abierta. P&L +$167.91. Capital $1,122.79 |
| Fase 3.5: VPS Deploy | **COMPLETA** | 4 servicios systemd en kaizen@168.231.86.93 |
| Fase 4: Dashboard | **COMPLETA (local)** | Next.js funcional en PC local (puerto 3000). Pendiente deploy a Vercel |
| Fase 5: Optimizacion | **EN CURSO** | Capa 1 pytest COMPLETA (75 tests). Capa 2 backtest pendiente |

---

## ESTADO DE VERSIONES

| Ubicacion | Version | Notas |
|-----------|---------|-------|
| **PC local** | e73d76b | Con todos los fixes de las sesiones 2026-03-28/29 |
| **GitHub** | e73d76b | Al dia |
| **VPS produccion** | e73d76b | Al dia — pull hecho 2026-03-29 |
| **Supabase DB** | Actualizada | cleanup_bad_signals.py ejecutado, portfolio reconstruido |

---

## Infraestructura (VPS — PRODUCCION)

**VPS:** kaizen@168.231.86.93 (Ubuntu 24, 2 CPUs, 8GB RAM) — hostname: kaiflow
**Repo:** https://github.com/flippy-03/polymarket-contrarian (privado)
**Deploy key:** generada en VPS, anadida a GitHub (read-only)
**SSH desde PC local:** clave en `~/.ssh/id_ed25519` (flippyopenclaw@gmail.com) — sin passphrase
**SSH root:** autorizado en /root/.ssh/authorized_keys.
**NOTA SSH:** SSH desde Claude Code no funciona actualmente (bug OpenSSH 10.2 en Git Bash/Windows). Usar Openclaw para ejecutar comandos en VPS.
**NOTA git en VPS:** Siempre usar `sudo -u kaizen git -C /home/kaizen/polymarket-contrarian ...` (no como root — falla por dubious ownership).

### Servicios systemd (arrancan solos al reiniciar)

| Servicio | Script | Log |
|----------|--------|-----|
| polymarket-collector | scripts/run_collector.py | logs/collector.log |
| polymarket-signal-engine | scripts/run_signal_engine.py | logs/signal_engine.log |
| polymarket-paper-trader | scripts/run_paper_trader.py | logs/paper_trader.log |
| polymarket-status-api | scripts/status_api.py | logs/status_api.log |

Los servicios corren como usuario `kaizen`, proyecto en `/home/kaizen/polymarket-contrarian/`.

### Workflow de deploy

```bash
# PC local: editar -> commit -> push
git push origin main

# En Openclaw (VPS):
sudo -u kaizen git -C /home/kaizen/polymarket-contrarian pull origin main
sudo systemctl restart polymarket-paper-trader polymarket-signal-engine polymarket-collector
```

### Status API (para Openclaw)

Puerto 8765, sin auth (solo acceso interno VPS).
Openclaw (Docker en mismo VPS) accede via `http://host.docker.internal:8765/status`

---

## Stats actuales (2026-03-29 19:30 UTC) — Run 2

Recalculadas tras cleanup_bad_signals.py (2026-03-29)

| Metrica | Valor |
|---------|-------|
| Run activa | Run 2 (inicio 2026-03-25T22:34 UTC) |
| Capital inicial | $1,000.00 |
| Capital actual | $1,122.79 |
| Trades cerrados | 16 (12W 4L) |
| P&L realizado | +$167.91 |
| P&L % | +16.8% |
| Win rate | 75% |
| Max drawdown | 6.3% |
| Loss streak actual | 0 (pico historico: 3) |
| Circuit breaker | off |
| Posiciones abiertas | 1 / 5 slots |

**Posicion abierta (run 2) — 2026-03-29:**

| Mercado | DIR | Entrada | Estado |
|---------|-----|---------|--------|
| Juan Pablo Velasco gubernatorial 2026 | NO | 0.550 | Activo, mercado sigue abierto |

---

## Arquitectura de archivos

```
src/
  data/
    polymarket_client.py      # CLOB + Gamma API wrapper
    polymarketscan_client.py  # PolymarketScan Public API (28 req/min)
    market_scanner.py         # Escanea y filtra mercados candidatos
    snapshot_collector.py     # Precio + orderbook cada 2 min. Ventana: 6-168h
    whale_trades_collector.py # Whale trades via PMS Agent API (?action=whales)
    falcon_client.py          # Falcon herding + whale trades (standby, API rota)
    leaderboard_seeder.py     # Top traders -> watched_wallets

  signals/
    divergence_detector.py    # detect_whale_herding_v2 + detect_price_velocity
    momentum_filter.py        # Score de momentum (0-100)
    contrarian_logic.py       # Smart wallet score + decision de senal
    signal_engine.py          # Combina todo -> DB signals. Ventana: 6-168h (alineada con collector)

  trading/
    risk_manager.py           # Kelly sizing, circuit breaker, drawdown
    paper_trader.py           # open_trade / close_trade con P&L
    position_manager.py       # Trailing stop, take profit, timeout, resolution
    portfolio_tracker.py      # Stats y resumen del portfolio

  utils/
    config.py                 # Todos los parametros de estrategia
    context_updater.py        # Actualiza CONTEXT.md
    logger.py                 # Loguru logger

scripts/
  run_collector.py            # Entry point Fase 1
  run_signal_engine.py        # Entry point Fase 2
  run_paper_trader.py         # Entry point Fase 3
  status_api.py               # HTTP API de monitoreo (puerto 8765, para Openclaw)
  run_cleanup.py              # Limpieza diaria
  setup_db.py                 # Verificar conexion y schema
  resolve_stuck_positions.py  # Cierre manual de posiciones sin snapshots + recalculo portfolio
  cleanup_bad_signals.py      # Expira senales invalidas + cierra trades con entry fuera de [0.20, 0.80]
  test_whale_apis.py          # Test manual de APIs whale

tests/
  unit/
    test_risk_manager.py      # Kelly (8), is_trading_allowed (9) — 17 tests
    test_position_manager.py  # _is_resolved (9), _is_expired (7), stop/TP (6) — 22 tests
    test_signal_filters.py    # Filtros de precio signal_engine: None, floors, ceiling, validos — 22 tests
    test_paper_trader_pnl.py  # P&L YES/NO win/loss, propiedades — 14 tests
  test_connections.py         # Integration tests (requieren .env real)

dashboard/                    # Fase 4 — Next.js (NO en git, deploy directo a Vercel)
  src/app/
    page.tsx                  # Dashboard principal (KPIs, equity curve, posiciones, senales, trades)
    analytics/page.tsx        # Analytics (historico completo, charts, calendar, export CSV)
    services/page.tsx         # Estado servicios systemd + circuit breaker + senales activas
    api/portfolio/route.ts    # GET portfolio_state
    api/trades/route.ts       # GET paper_trades con filtros
    api/positions/route.ts    # GET posiciones abiertas con P&L no realizado
    api/signals/route.ts      # GET senales por estado
    api/stats/route.ts        # GET analytics completos
  src/components/
    Sidebar.tsx               # Nav fija con indicador Running/Paused en tiempo real
    KpiCard.tsx               # Card de metrica con variantes de color
    TimeFilter.tsx            # Filtro de periodo temporal
  src/lib/
    supabase.ts               # Cliente Supabase server-side (service role key)
    hooks.ts                  # useAutoRefresh, formatPnl, formatPct, pnlColor, timeAgo
    types.ts                  # TypeScript interfaces (PaperTrade, PortfolioState, Signal...)
```

---

## Dashboard (Fase 4) — Notas tecnicas

- **Stack:** Next.js 16.2.1 + Tailwind v4 + Recharts 3.8.1 + Supabase JS
- **Tema:** dark SaaS, CSS custom properties (--bg-primary, --green, --red, --blue...)
- **Auto-refresh:** 30s en Dashboard, 60s en Analytics
- **Puerto dev:** 3000 (antes 3001 — ya no hay conflicto)
- **DB schema critico:**
  - `pnl_usd`, `pnl_pct` (decimal, NO porcentaje — multiplicar x100 para display)
  - `shares`, `position_usd` (NO quantity/position_size)
  - `pnl_pct` almacenado como decimal: -0.2857 = -28.57%
- **Drawdown en dashboard:** usa `(initial_capital - current_capital) / initial_capital` (actual), NO `max_drawdown` de la DB (historico)
- **Indicador Running/Paused:** en Sidebar, misma logica que risk_manager.is_trading_allowed()
- **Equity curve:** ordenada por `closed_at` (fix 2026-03-29 — antes ordenaba por opened_at causando puntos fuera de orden)
- **Analytics:** auto-selecciona run mas reciente al cargar (fix 2026-03-29 — antes defaulteaba a "All Runs" mostrando 21 en vez de 17 trades)
- **Deploy pendiente:** Vercel — requiere SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY como env vars

---

## Decisiones de diseno

### APIs
- **Polymarket Gamma API** — fuente principal de mercados
- **Polymarket CLOB API** — precios en tiempo real (404 en AMM-only es normal, en DEBUG)
- **PolymarketScan Public API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api` (28 req/min)
- **PolymarketScan Agent API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api` (60 req/min, sin auth). `?action=whales&limit=50&agent_id=contrarian-bot`
- **Falcon API** — `https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized` POST. Bearer token en .env. ESTADO: devuelve 400 server-side. Graceful fallback implementado.

### Estrategia
- Divergencia proxy v1: whale herding + velocidad de precio > 5% en 1h
- Fallback sin whale data: velocidad-only >= 5%/1h
- Seleccion: top 500 por score compuesto = vol*0.3 + proximidad*0.4 + velocidad*0.3
- Pesos del score: divergencia 50%, momentum 30%, smart wallet 20%
- Threshold de senal: 65/100
- **Rango valido de entrada: [0.20, 0.80]** (simetrico, ambas direcciones)
  - < 0.20: mercado cerca de resolverse en direccion opuesta (MIN_CONTRARIAN_PRICE)
  - > 0.80: take-profit matematicamente inalcanzable en mercado binario (ceiling anadido 2026-03-28)
- **Ventana de mercados:** 6-168h hasta resolucion (alineada entre collector y signal engine — fix 2026-03-29)

### Risk management
- Half-Kelly sizing (Kelly x 0.5), max 5% capital por trade
- Max 5 posiciones abiertas simultaneas
- Circuit breaker: 3 perdidas consecutivas -> pausa 24h
- Max drawdown: 20% -> pausa
- Trailing stop: 25% | Take profit: 50%

### Paper trader: precio de entrada
- `open_trade()` usa `price_at_signal`, NO el precio actual del mercado
- Validacion pre-trade: bloquea si mercado resuelto (yes_price >= 0.97 o <= 0.03) o drift > 40%

---

## Historial de bugs resueltos

| Bug | Resuelto | Descripcion |
|-----|----------|-------------|
| whale_trades Public API devuelve [] | 2026-03-24 | Migrado a Agent API |
| Falcon parameterized 400 | Bloqueado (server-side) | Graceful fallback implementado |
| Filtro sports no funcionaba | 2026-03-22 | Filtro por keywords en pregunta |
| Mercados sub-$0.05 generaban senales | 2026-03-22 | MIN_ENTRY_PRICE=0.05 |
| position_manager: trailing stop/TP/timeout nunca ejecutaban | 2026-03-25 | Bug elif chain — fix: if close_reason is None |
| Senales antiguas en mercados ya resueltos | 2026-03-25 | Validacion pre-trade |
| Snapshot collector sin paginacion | 2026-03-28 | Paginado + alineacion con signal engine |
| YES entries < 0.20 (mercados 80%+ resueltos) | 2026-03-28 | MIN_CONTRARIAN_PRICE=0.20 |
| NO entries con entry > 0.80 (TP inalcanzable) | 2026-03-28 | Ceiling simetrico en signal_engine |
| price=None saltaba todos los filtros en signal_engine | 2026-03-28 | Hard skip si sin precio |
| 4 posiciones abiertas sin snapshots (mercados expirados) | 2026-03-28 | resolve_stuck_positions.py |
| portfolio_state desincronizado (drawdown 22.6%, capital $835) | 2026-03-28 | Reconstruido desde trade history |
| Dashboard mostraba P&L $0 en Analytics | 2026-03-28 | Nombres de columna incorrectos |
| signal_engine seleccionaba mercados fuera de ventana 6-168h | 2026-03-29 | Alineado con filtros del collector — no_data baja de 494 a 220 |
| Paper trader spam "Position too small" con senales invalidas | 2026-03-29 | cleanup_bad_signals.py — expira senales con entry fuera de [0.20,0.80] |
| Posicion YES@0.055 abierta con codigo buggy | 2026-03-29 | Cerrada via cleanup_bad_signals.py (exit=0.0585, +$3.56) |
| Dashboard equity curve con punto fuera de orden (ATH en pasado) | 2026-03-29 | Sort por closed_at antes de acumular PnL |
| Dashboard Analytics mostraba 21 trades en vez de 17 | 2026-03-29 | Auto-seleccion del run mas reciente al cargar |

---

## Parametros clave (config.py)

```python
MIN_VOLUME_24H              = 10_000
MIN_HOURS_TO_RESOLUTION     = 6
MAX_HOURS_TO_RESOLUTION     = 168
SIGNAL_THRESHOLD            = 65
INITIAL_CAPITAL             = 1000.0
MIN_ENTRY_PRICE             = 0.05
MAX_SIGNAL_DRIFT_PCT        = 0.40
MIN_CONTRARIAN_PRICE        = 0.20     # floor — no fadear mercados 80%+ resueltos
# ceiling implicito: entry <= 1 - MIN_CONTRARIAN_PRICE = 0.80 (en signal_engine)
TRAILING_STOP_PCT           = 0.25
TAKE_PROFIT_PCT             = 0.50
MAX_DRAWDOWN_PCT            = 0.20
KELLY_FRACTION              = 0.5
MAX_POSITION_SIZE_PCT       = 0.05
CIRCUIT_BREAKER_LOSSES      = 3
CIRCUIT_BREAKER_COOLDOWN_HOURS = 24
```

---

## Credenciales y entorno

- `.env` en raiz del proyecto (no commitear)
- Python 3.12 en VPS, venv en `.venv/`
- Supabase URL: `https://pdmmvhshorwfqseattvz.supabase.co`

---

## Test Suite — Estado (Fase 5)

### Capa 1 — pytest puro (COMPLETA — 75/75 tests passing)

Ejecutar: `python -m pytest tests/unit/ -v`

| Archivo | Tests | Cobertura |
|---------|-------|-----------|
| test_risk_manager.py | 17 | Kelly sizing, is_trading_allowed (CB, DD, max_pos) |
| test_position_manager.py | 22 | _is_resolved, _is_expired, stop/TP thresholds |
| test_signal_filters.py | 22 | Filtros precio: None, near-resolution, floor, ceiling, validos |
| test_paper_trader_pnl.py | 14 | P&L YES/NO win/loss, propiedades matematicas |

### Capa 2 — Backtest/replay script (PENDIENTE)

Plan:
- Lee `market_snapshots` historicos de la DB (sin modificar nada)
- Toma trades reales de `paper_trades` como punto de partida
- Pasa cada snapshot por la logica de `position_manager` (stop/TP/timeout/resolution)
- Compara decision simulada vs decision real tomada por el bot
- Produce informe JSON: acuerdos, discrepancias, P&L simulado vs real
- Objetivo: validar que position_manager se comporta correctamente con datos reales

### Capa 3 (opcional) — Run 0 en DB

Para validar flujo de escritura completo una vez con datos reales pero aislados.

---

## Proximo paso

Capa 2: script de backtest/replay con snapshots reales.
