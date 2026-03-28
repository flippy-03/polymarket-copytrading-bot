# Polymarket Contrarian Bot — Project Context

> Actualizado: 2026-03-28 23:45 UTC
> Actualizado manualmente tras cada sesion de trabajo. Editar manualmente para notas permanentes.

---

## Estado de fases

| Fase | Estado | Descripcion |
|------|--------|-------------|
| Fase 1: Data Collection | **COMPLETA** | Collector corriendo 24/7 en VPS |
| Fase 2: Signal Engine | **COMPLETA** | Engine con whale data v2 (PMS Agent API activo) |
| Fase 3: Paper Trading | **EN CURSO** | Run 2: 20 trades (11W 4L + 1 abierta). P&L +$164.35. Capital $1,119.23 |
| Fase 3.5: VPS Deploy | **COMPLETA** | 4 servicios systemd en kaizen@168.231.86.93 |
| Fase 4: Dashboard | **COMPLETA (local)** | Next.js funcional en PC local. Pendiente deploy a Vercel |
| Fase 5: Optimizacion | Pendiente | Test suite + ajuste de thresholds con datos reales |

---

## ESTADO DE VERSIONES — CRITICO

| Ubicacion | Version | Notas |
|-----------|---------|-------|
| **PC local** | ULTIMA — con todos los fixes de hoy | Sin commitear todavia |
| **GitHub** | Commit 0e69588 (2026-03-28 manana) | Sin los fixes de hoy |
| **VPS produccion** | Commit 0e69588 | signal_engine con bugs sigue activo |
| **Supabase DB** | Actualizada | resolve_stuck_positions ya ejecutado |

**ACCION PENDIENTE:** commit + push + deploy al VPS antes de que el signal_engine genere mas senales malas.

Comandos deploy (ejecutar desde PC local, luego en Openclaw):
```bash
# PC local:
cd /Users/flipp/Documents/polymarket-contrarian
git add src/signals/signal_engine.py scripts/resolve_stuck_positions.py
git commit -m "Fix signal_engine: block missing price, symmetric entry ceiling [0.20-0.80]"
git push origin main

# En Openclaw (VPS):
cd /home/kaizen/polymarket-contrarian && sudo -u kaizen git pull origin main
sudo systemctl restart polymarket-signal-engine polymarket-paper-trader
```

Nota: el dashboard NO se commitea (es carpeta nueva con .env.local — deploy va directo a Vercel).

---

## Infraestructura (VPS — PRODUCCION)

**VPS:** kaizen@168.231.86.93 (Ubuntu 24, 2 CPUs, 8GB RAM) — hostname: kaiflow
**Repo:** https://github.com/flippy-03/polymarket-contrarian (privado)
**Deploy key:** generada en VPS, anadida a GitHub (read-only)
**SSH desde PC local:** clave en `~/.ssh/id_ed25519` (flippyopenclaw@gmail.com) — sin passphrase
**SSH root:** autorizado en /root/.ssh/authorized_keys.
**NOTA SSH:** SSH desde Claude Code no funciona actualmente (bug OpenSSH 10.2 en Git Bash/Windows). Usar Openclaw para ejecutar comandos en VPS.

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
cd /home/kaizen/polymarket-contrarian && sudo -u kaizen git pull origin main
sudo systemctl restart polymarket-paper-trader polymarket-signal-engine polymarket-collector
```

### Status API (para Openclaw)

Puerto 8765, sin auth (solo acceso interno VPS).
Openclaw (Docker en mismo VPS) accede via `http://host.docker.internal:8765/status`

---

## Stats actuales (2026-03-28 23:45 UTC) — Run 2

Recalculadas tras cerrar 4 posiciones atascadas con resolve_stuck_positions.py

| Metrica | Valor |
|---------|-------|
| Run activa | Run 2 (inicio 2026-03-25T22:34 UTC) |
| Capital inicial | $1,000.00 |
| Capital actual | $1,119.23 |
| Trades totales | 20 (11W 4L + 1 abierta) |
| P&L realizado | +$164.35 |
| P&L % | +16.4% |
| Win rate | 73.3% |
| Max drawdown | 4.1% |
| Loss streak actual | 0 |
| Circuit breaker | off |
| Posiciones abiertas | 1 / 5 slots |

**Posicion abierta (run 2) — 2026-03-28 23:45 UTC:**

| Mercado | DIR | Entrada | yes_price actual | Estado |
|---------|-----|---------|-----------------|--------|
| Juan Pablo Velasco gubernatorial 2026 | NO | 0.550 | 0.369 | Activo, mercado sigue abierto |

---

## Historia de posiciones cerradas — Run 2

| Mercado | DIR | Entrada | Salida | P&L | Razon |
|---------|-----|---------|--------|-----|-------|
| ETH > $2100 March 26 | NO | 0.650 | 1.000 | +$23.56 | RESOLUTION |
| BTC > $70k March 26 | NO | 0.730 | 1.000 | +$18.50 | RESOLUTION |
| Kanye BULLY by March 27 | NO | 0.710 | 1.000 | +$17.95 | RESOLUTION |
| Avalanche Spread (-1.5) | YES | 0.550 | 1.000 | +$38.86 | RESOLUTION |
| (otros 7 wins + 4 losses) | — | — | — | +$65.48 | varios |

Nota: las 4 primeras filas estaban atascadas (sin snapshots por mercados expirados). Cerradas manualmente via resolve_stuck_positions.py el 2026-03-28 con precios verificados en Gamma API.

---

## Arquitectura de archivos

```
src/
  data/
    polymarket_client.py      # CLOB + Gamma API wrapper
    polymarketscan_client.py  # PolymarketScan Public API (28 req/min)
    market_scanner.py         # Escanea y filtra mercados candidatos
    snapshot_collector.py     # Precio + orderbook cada 2 min
    whale_trades_collector.py # Whale trades via PMS Agent API (?action=whales)
    falcon_client.py          # Falcon herding + whale trades (standby, API rota)
    leaderboard_seeder.py     # Top traders -> watched_wallets

  signals/
    divergence_detector.py    # detect_whale_herding_v2 + detect_price_velocity
    momentum_filter.py        # Score de momentum (0-100)
    contrarian_logic.py       # Smart wallet score + decision de senal
    signal_engine.py          # Combina todo -> DB signals

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
  test_whale_apis.py          # Test manual de APIs whale

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
- **Puerto dev:** 3001 (3000 ocupado por otra app)
- **DB schema critico:**
  - `pnl_usd`, `pnl_pct` (decimal, NO porcentaje — multiplicar x100 para display)
  - `shares`, `position_usd` (NO quantity/position_size)
  - `pnl_pct` almacenado como decimal: -0.2857 = -28.57%
- **Drawdown en dashboard:** usa `(initial_capital - current_capital) / initial_capital` (actual), NO `max_drawdown` de la DB (historico)
- **Indicador Running/Paused:** en Sidebar, misma logica que risk_manager.is_trading_allowed()
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
| 4 posiciones abiertas sin snapshots (mercados expirados) | 2026-03-28 | resolve_stuck_positions.py — cerradas con precios Gamma API |
| portfolio_state desincronizado (drawdown 22.6%, capital $835) | 2026-03-28 | Reconstruido desde trade history: capital $1119, +16.4%, 73.3% WR |
| Dashboard mostraba P&L $0 en Analytics | 2026-03-28 | Nombres de columna incorrectos (pnl vs pnl_usd, quantity vs shares) |

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

## Proximo paso: Test Suite (Fase 5 prep)

Plan acordado (2026-03-28):

**Capa 1 — pytest puro** (sin DB, determinista, repeatable):
Casos a cubrir:
- Filtros de precio signal_engine: 8 casos limite (None, <0.05, >0.95, <0.20, >0.80, valido)
- Kelly sizing: edge=0, edge negativo, posicion < $1, cap al 5%
- Circuit breaker: 0/2/3 perdidas, CB activo, CB expirado
- is_trading_allowed: CB activo, DD >= 20%, max_positions, ok
- Resolucion mercado: yes_price 0.97, 0.03, 0.50, None
- Trailing stop / TP: exactamente en umbral, encima, debajo
- Timeout: 6d, 7d exacto, 8d
- P&L: YES ganador, YES perdedor, NO ganador, NO perdedor

**Capa 2 — script backtest/replay** (lee snapshots reales, sin modificar DB):
- Lee market_snapshots historicos
- Pasa por logica de position_manager con codigo actual
- Produce informe JSON con resultados simulados
- Valida position_manager end-to-end con datos reales

**Run 0 en DB (opcional):** para validar flujo de escritura completo una vez.
