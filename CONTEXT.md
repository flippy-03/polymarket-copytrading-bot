# Polymarket Contrarian Bot — Project Context

> Actualizado: 2026-03-25 22:40 UTC
> Actualizado cada 12h por run_collector.py. Editar manualmente para notas permanentes.

---

## Estado de fases

| Fase | Estado | Descripcion |
|------|--------|-------------|
| Fase 1: Data Collection | **COMPLETA** | Collector corriendo 24/7 en VPS |
| Fase 2: Signal Engine | **COMPLETA** | Engine con whale data v2 (PMS Agent API activo) |
| Fase 3: Paper Trading | **EN CURSO** | Run 2 limpia desde 2026-03-25. 4 trades abiertos |
| Fase 3.5: VPS Deploy | **COMPLETA** | 4 servicios systemd en kaizen@187.124.45.248 |
| Fase 4: Dashboard | Pendiente | Next.js en Vercel |
| Fase 5: Optimizacion | Pendiente | Ajustar thresholds con datos reales |

---

## Infraestructura (VPS — PRODUCCION)

**VPS:** kaizen@187.124.45.248 (Ubuntu 24, 2 CPUs, 8GB RAM)
**Repo:** https://github.com/flippy-03/polymarket-contrarian (privado)
**Deploy key:** generada en VPS, añadida a GitHub (read-only)
**SSH desde PC local:** clave en `~/.ssh/id_ed25519` (flippyopenclaw@gmail.com) — sin passphrase para acceso desde Claude Code
**SSH root:** tambien autorizado (clave añadida a /root/.ssh/authorized_keys el 2026-03-25)

### Servicios systemd (arrancan solos al reiniciar)

| Servicio | Script | Log |
|----------|--------|-----|
| polymarket-collector | scripts/run_collector.py | logs/collector.log |
| polymarket-signal-engine | scripts/run_signal_engine.py | logs/signal_engine.log |
| polymarket-paper-trader | scripts/run_paper_trader.py | logs/paper_trader.log |
| polymarket-status-api | scripts/status_api.py | logs/status_api.log |

Los servicios corren como usuario `kaizen`, proyecto en `/home/kaizen/polymarket-contrarian/`.

### Status API (para Openclaw)

Puerto 8765, sin auth (solo acceso interno VPS).
Openclaw (Docker en mismo VPS) accede via `http://host.docker.internal:8765/status`

| Endpoint | Contenido |
|----------|-----------|
| GET /status | Estado servicios + portfolio completo (JSON) |
| GET /logs/collector | Ultimas 50 lineas collector.log |
| GET /logs/signals | Ultimas 50 lineas signal_engine.log |
| GET /logs/trader | Ultimas 50 lineas paper_trader.log |
| GET /healthz | Ping simple |

### Workflow de deploy

```bash
# Desde PC local: editar -> commit -> push -> pull en VPS
git push origin main
ssh root@187.124.45.248 "cd /home/kaizen/polymarket-contrarian && sudo -u kaizen git pull origin main"
# Restart servicios (requiere sudo desde Openclaw):
# sudo systemctl restart polymarket-paper-trader polymarket-signal-engine polymarket-collector
```

### Comandos de operacion (desde Claude Code / PC local)

```bash
# Ver logs en tiempo real
ssh -i ~/.ssh/id_ed25519 root@187.124.45.248 "tail -50 /home/kaizen/polymarket-contrarian/logs/paper_trader.log"
# Ver estado de servicios
ssh -i ~/.ssh/id_ed25519 root@187.124.45.248 "systemctl is-active polymarket-collector polymarket-signal-engine polymarket-paper-trader polymarket-status-api"
# Ver status via API
ssh -i ~/.ssh/id_ed25519 root@187.124.45.248 "curl -s http://localhost:8765/status"
```

---

## Stats actuales (2026-03-25 22:40 UTC) — Run 2

| Metrica | Valor |
|---------|-------|
| Snapshots en DB | 400k+ (acumulando en VPS) |
| Mercados activos | ~4,500 |
| Run activa | Run 2 (inicio 2026-03-25T22:34 UTC) |
| Capital | $1,000.00 (inicio run 2) |
| Trades abiertos | 4 |
| Trades cerrados | 1 (RESOLUTION, -$40.73) |
| P&L realizado | -$40.73 |
| Unrealized P&L | +$2.95 |
| Circuit breaker | OK |

**Trades abiertos (run 2):**
- NO @ 0.760 — señal 2026-03-25T21:39
- YES @ 0.550 — señal 2026-03-25T00:51
- NO @ 0.550 — señal 2026-03-25T00:20
- NO @ 0.260 — señal 2026-03-25T22:20

**Nota run 1 (archivada):** 10 trades con bugs — trailing stop/TP nunca ejecutaron. Capital final $770. Datos conservados en DB con run_id=1 para histórico UI.

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
    context_updater.py        # Actualiza CONTEXT.md cada 12h
    logger.py                 # Loguru logger

scripts/
  run_collector.py            # Entry point Fase 1
  run_signal_engine.py        # Entry point Fase 2
  run_paper_trader.py         # Entry point Fase 3
  status_api.py               # HTTP API de monitoreo (puerto 8765, para Openclaw)
  run_cleanup.py              # Limpieza diaria
  setup_db.py                 # Verificar conexion y schema
  test_whale_apis.py          # Test manual de APIs whale
```

---

## Decisiones de diseno

### APIs
- **Polymarket Gamma API** — fuente principal de mercados
- **Polymarket CLOB API** — precios en tiempo real (404 en AMM-only es normal, en DEBUG)
- **PolymarketScan Public API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api` (28 req/min)
- **PolymarketScan Agent API** — `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api` (60 req/min, sin auth). `?action=whales&limit=50&agent_id=contrarian-bot` reemplaza endpoint whale_trades del Public API que devolvía []
- **Falcon API** — `https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized` POST. Bearer token en .env. Agent IDs: 575 (Market Insights), 556 (Whale Trades). ESTADO: devuelve 400 por error server-side. Graceful fallback implementado.

### Integracion whale data (COMPLETA — 2026-03-24)

Prioridad en `detect_whale_herding_v2()`:
1. **Falcon Market Insights** (agent_id=575) — top1_wallet_pct > 30% = herding fuerte. Standby (API rota server-side).
2. **PMS Agent API** (action=whales) — ACTIVO. 50 trades, ~21-32 mercados directionales por ciclo.
3. **Snapshot-based** (detect_whale_herding) — lee whale_direction de DB. Fallback si mercado no aparece en PMS.
4. **Momentum de precio** (>5% en 1h) — ultimo fallback cuando sample_size == 0.

### Estrategia
- Divergencia proxy v1: whale herding + velocidad de precio > 5% en 1h
- Fallback sin whale data: velocidad-only >= 5%/1h, divergence_score = vel_norm * 100
- Seleccion de mercados: top 500 por score compuesto = vol*0.3 + proximidad*0.4 + velocidad*0.3 (min vol $1k)
- Pesos del score: divergencia 50%, momentum 30%, smart wallet 20%
- Threshold de senal: 65/100
- Categorias excluidas: sports (filtro por keywords en pregunta, no por campo category que llega vacio)
- Ventana de mercados: 6h a 7d hasta resolucion

### Risk management
- Half-Kelly sizing (Kelly x 0.5), max 5% capital por trade
- Max 5 posiciones abiertas simultaneas
- Circuit breaker: 3 perdidas consecutivas -> pausa 24h
- Max drawdown: 20% -> pausa
- Trailing stop: 25% | Take profit: 50%

### Paper trader: precio de entrada (CRITICO)
- `open_trade()` usa `price_at_signal`, NO el precio actual del mercado
- Por que: en produccion el trader ejecuta segundos despues de la senal. En dev local el PC esta apagado a ratos — precio actual seria incorrecto y sesgaría el backtesting
- `_get_current_price()` sigue usandose en `position_manager.py` para trailing stop/TP (correcto)

### Validacion de condiciones antes de abrir trade (añadido 2026-03-25)
- Antes de ejecutar, `open_trade()` consulta el precio actual del mercado y bloquea si:
  1. **Mercado resuelto**: yes_price >= 0.97 o <= 0.03 → señal marcada EXPIRED
  2. **Drift excesivo**: precio actual difiere >40% del precio de la señal → señal marcada EXPIRED
- Motivacion: senales antiguas (bloqueadas por circuit breaker) podian ejecutarse sobre mercados ya resueltos o con hipotesis invalidada por el movimiento del precio

### Filtros de calidad de senales
- Sports: ~818 mercados eliminados por keywords en pregunta (category de la API es poco fiable)
- Precio minimo MIN_ENTRY_PRICE=0.05. Aplica en ambas direcciones:
  - YES signal: yes_price < 0.05 -> skip (entrada sub-penny)
  - YES signal: yes_price > 0.95 -> skip (mercado casi resuelto YES, sin edge)
  - NO signal: yes_price < 0.05 -> skip (mercado casi resuelto NO, sin edge)
  - NO signal: 1 - yes_price < 0.05 -> skip (entrada sub-penny)

### Multi-run / historico
- Tabla `runs` en Supabase: id, started_at, ended_at, note
- `paper_trades` y `portfolio_state` tienen columna `run_id`
- `get_portfolio_state()` siempre coge el run_id mas alto (run activa)
- Nuevas trades heredan run_id del portfolio_state activo
- Run 1 archivada con nota "bug trailing stop/TP inactivo"

### Datos
- `clobTokenIds` puede llegar como JSON string o lista Python — normalizer maneja ambos
- Mercados con token IDs < 10 chars se consideran corruptos y se nullean
- Snapshots sin precio (CLOB 404) se descartan

---

## Historial de bugs resueltos

| Bug | Estado | Descripcion |
|-----|--------|-------------|
| whale_trades Public API devuelve [] | Resuelto (2026-03-24) | Migrado a Agent API. 50 trades/llamada |
| Falcon parameterized endpoint devuelve 400 | Bloqueado (server-side) | Graceful fallback. PMS Agent API es fuente primaria |
| Filtro sports no funcionaba | Resuelto (2026-03-22) | Gamma devuelve category vacio. Filtro por keywords |
| Mercados sub-$0.05 generaban senales | Resuelto (2026-03-22) | MIN_ENTRY_PRICE=0.05 |
| Senales en mercados casi resueltos | Resuelto (2026-03-23) | Filtro yes_price > 0.95 / < 0.05 |
| position_manager: RESOLUTION como TRAILING_STOP | Resuelto (2026-03-22) | _is_resolved() detecta ambas direcciones |
| Paper trader usaba precio actual en vez de price_at_signal | Resuelto (2026-03-22) | open_trade() usa price_at_signal |
| **position_manager: trailing stop/TP/timeout nunca ejecutaban** | **Resuelto (2026-03-25)** | Bug elif chain: checks 2-4 encadenados al if raw_yes. Fix: if close_reason is None |
| Senales antiguas abrian trades en mercados ya resueltos | Resuelto (2026-03-25) | Validacion pre-trade: resolved + drift >40% -> EXPIRED |
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
MAX_SIGNAL_DRIFT_PCT        = 0.40     # Drift maximo pre-trade (hipotesis invalidada)
TRAILING_STOP_PCT           = 0.25
TAKE_PROFIT_PCT             = 0.50
MAX_DRAWDOWN_PCT            = 0.20
# signal_engine internos:
#   _MIN_VOLUME = 1_000
#   _CANDIDATE_TOP_N = 500
#   fallback velocity threshold = 0.05 (5%)
```

---

## Credenciales y entorno

- `.env` en raiz del proyecto (no commitear — esta en .gitignore)
- Python 3.12 en VPS (3.11+ requerido), venv en `.venv/`
- Supabase URL: `https://pdmmvhshorwfqseattvz.supabase.co`
- PolymarketScan Public API: `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api`
- PolymarketScan Agent API: `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/agent-api`
- Falcon/narrative API: `https://narrative.agent.heisenberg.so` — Bearer token en .env

---

## Proximo paso inmediato

**Fase 4 Dashboard (cuando se cumplan):**
- [x] Al menos 1 senal generada
- [x] Al menos 1 trade abierto
- [x] 48h de datos limpios
- [ ] Al menos 1 trade limpio cerrado (post run 2 — en curso)

**Pendientes tecnicos:**
- `get_active_markets_from_db` sin paginacion (bajo riesgo, monitorizar si DB crece)
- Falcon API: re-activar cuando corrijan el endpoint /parameterized server-side
