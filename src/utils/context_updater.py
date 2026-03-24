"""
Context updater — rewrites CONTEXT.md with current project stats.
Called automatically every 12h from run_collector.py.
"""

from datetime import datetime, timezone
from pathlib import Path

from src.db import supabase_client as db
from src.trading.risk_manager import get_portfolio_state
from src.utils.logger import logger

CONTEXT_PATH = Path(__file__).parent.parent.parent / "CONTEXT.md"


def _get_stats() -> dict:
    client = db.get_client()

    # Snapshots (paginated count)
    snap_count = 0
    offset = 0
    while True:
        batch = client.table("market_snapshots").select("id", count="exact").range(offset, offset + 999).execute()
        snap_count = batch.count  # count is always total
        break  # count is returned on first call

    # Markets
    markets = client.table("markets").select("id,yes_token_id", count="exact").execute()
    total_markets = markets.count
    with_token = sum(1 for r in markets.data if r.get("yes_token_id") and len(str(r["yes_token_id"])) >= 10)

    # Signals
    signals = client.table("signals").select("id,status").execute()
    total_signals = len(signals.data)
    active_signals = sum(1 for s in signals.data if s["status"] == "ACTIVE")

    # Trades
    trades = client.table("paper_trades").select("id,status,pnl_usd").execute()
    total_trades = len(trades.data)
    open_trades = sum(1 for t in trades.data if t["status"] == "OPEN")
    closed_trades = [t for t in trades.data if t["status"] == "CLOSED"]
    total_pnl = sum(float(t["pnl_usd"] or 0) for t in closed_trades)

    # Portfolio
    portfolio = get_portfolio_state(client) or {}

    # Wallets
    wallets = client.table("watched_wallets").select("id", count="exact").execute()

    # Latest snapshot time
    latest_snap = (
        client.table("market_snapshots")
        .select("snapshot_at")
        .order("snapshot_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    latest_snap_time = latest_snap[0]["snapshot_at"][:16] if latest_snap else "none"

    return {
        "snap_count": snap_count,
        "total_markets": total_markets,
        "with_token": with_token,
        "total_signals": total_signals,
        "active_signals": active_signals,
        "total_trades": total_trades,
        "open_trades": open_trades,
        "closed_trades": len(closed_trades),
        "total_pnl": total_pnl,
        "portfolio": portfolio,
        "wallets": wallets.count,
        "latest_snap_time": latest_snap_time,
    }


def update_context() -> None:
    try:
        s = _get_stats()
        p = s["portfolio"]
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        capital = float(p.get("current_capital", 1000))
        initial = float(p.get("initial_capital", 1000))
        pnl_pct = (capital - initial) / initial * 100
        circuit = "BROKEN [X]" if p.get("is_circuit_broken") else "OK [v]"
        win_rate = float(p.get("win_rate", 0)) * 100

        content = f"""# Polymarket Contrarian Bot — Project Context

> Actualizado automaticamente: {now}
> Actualizado cada 12h por run_collector.py. Editar manualmente para notas permanentes.

---

## Estado de fases

| Fase | Estado | Descripcion |
|------|--------|-------------|
| Fase 1: Data Collection | **COMPLETA** | Collector corriendo, snapshots acumulando |
| Fase 2: Signal Engine | **COMPLETA** | Engine implementado, generando senales |
| Fase 3: Paper Trading | **COMPLETA** | Motor construido y testeado |
| Fase 4: Dashboard | Pendiente | Next.js en Vercel |
| Fase 5: Optimizacion | Pendiente | Ajustar thresholds con datos reales |

---

## Stats actuales ({now})

| Metrica | Valor |
|---------|-------|
| Snapshots en DB | {s['snap_count']:,} |
| Ultimo snapshot | {s['latest_snap_time']} UTC |
| Mercados totales | {s['total_markets']:,} |
| Mercados con token ID valido | {s['with_token']:,} |
| Wallets watched | {s['wallets']} |
| Senales generadas | {s['total_signals']} ({s['active_signals']} activas) |
| Trades paper total | {s['total_trades']} ({s['open_trades']} abiertos, {s['closed_trades']} cerrados) |
| P&L total | ${s['total_pnl']:+.2f} |
| Capital actual | ${capital:.2f} (inicio: ${initial:.2f}, {pnl_pct:+.1f}%) |
| Win rate | {win_rate:.0f}% |
| Circuit breaker | {circuit} |

---

## Como arrancar

```powershell
# Terminal 1 - Data Collection
python scripts/run_collector.py

# Terminal 2 - Signal Engine
python scripts/run_signal_engine.py

# Terminal 3 - Paper Trader
python scripts/run_paper_trader.py

# Terminal 4 - Cleanup (opcional, una vez al dia)
python scripts/run_cleanup.py --schedule
```

**Nota:** Correr siempre desde la raiz del proyecto.

---

## Arquitectura de archivos

```
src/
  data/
    polymarket_client.py      # CLOB + Gamma API wrapper
    polymarketscan_client.py  # PolymarketScan API wrapper (rate limit 28 req/min)
    market_scanner.py         # Escanea y filtra mercados candidatos
    snapshot_collector.py     # Precio + orderbook cada 2 min
    whale_trades_collector.py # Whale trades para deteccion de herding
    leaderboard_seeder.py     # Top traders -> watched_wallets

  signals/
    divergence_detector.py    # Herding de ballenas + velocidad de precio
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
    context_updater.py        # Actualiza este archivo automaticamente
    logger.py                 # Loguru logger

scripts/
  run_collector.py            # Entry point Fase 1 (incluye context update cada 12h)
  run_signal_engine.py        # Entry point Fase 2
  run_paper_trader.py         # Entry point Fase 3
  run_cleanup.py              # Limpieza diaria de snapshots antiguos
  setup_db.py                 # Verificar conexion y schema
```

---

## Decisiones de diseno

### APIs
- **Polymarket Gamma API** -- fuente principal de mercados
- **Polymarket CLOB API** -- precios en tiempo real (404 en mercados AMM-only es normal, logueado en DEBUG)
- **PolymarketScan API** -- whale trades, leaderboard, wallet profiles. Rate limit: 28 req/min
- La divergencia AI vs Humanos se construye por nosotros (no hay endpoint directo)

### Estrategia
- **Divergencia proxy v1:** whale herding + velocidad de precio > 5% en 1h
- **Pesos del score:** divergencia 50%, momentum 30%, smart wallet 20%
- **Threshold de senal:** 65/100
- **Categorias excluidas:** sports
- **Ventana de mercados:** 6h a 7d hasta resolucion

### Risk management
- Half-Kelly sizing (Kelly x 0.5), max 5% capital por trade
- Max 5 posiciones abiertas simultaneas
- Circuit breaker: 3 perdidas consecutivas -> pausa 24h
- Max drawdown: 20% -> pausa
- Trailing stop: 25% | Take profit: 50%

### Datos
- `clobTokenIds` puede llegar como JSON string o lista Python -- el normalizer maneja ambos
- Mercados con token IDs < 10 chars se consideran corruptos y se nullean
- Snapshots sin precio (CLOB 404) se descartan

### Encoding
- Windows CP1252 no soporta emojis -- los logs usan ASCII puro

---

## Bugs conocidos

| Bug | Estado | Descripcion |
|-----|--------|-------------|
| 0 senales generadas | En observacion | Normal con <48h de datos. Thresholds estrictos por diseno |
| CLOB 404 masivos | Resuelto (silenciado) | Mercados AMM-only, logueados en DEBUG |
| Leaderboard solo 29 wallets | Limitacion API | PolymarketScan retorna 29 en lugar de 100 |
| get_active_markets_from_db sin paginacion | Pendiente | Retorna max 1000 mercados. Fix: anadir paginacion |

---

## Parametros clave (config.py)

```python
DIVERGENCE_THRESHOLD_MIN    = 0.10
DIVERGENCE_THRESHOLD_STRONG = 0.15
MIN_VOLUME_24H              = 10_000
MIN_LIQUIDITY               = 5_000
MIN_HOURS_TO_RESOLUTION     = 6
MAX_HOURS_TO_RESOLUTION     = 168
SIGNAL_THRESHOLD            = 65
INITIAL_CAPITAL             = 1000.0
```

---

## Credenciales y entorno

- `.env` en la raiz del proyecto (no commitear)
- Python: 3.14 (sistema, no venv -- el venv en `.venv/` esta vacio)
- Supabase URL: `https://pdmmvhshorwfqseattvz.supabase.co`
- PolymarketScan API: `https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api`

---

## Proximo paso

**Fase 4: Dashboard** (Next.js en Vercel)

Esperar antes de empezar:
- [ ] Al menos 1 senal generada (validar signal engine end-to-end)
- [ ] Al menos 1 trade paper abierto y cerrado
- [ ] 48h de datos acumulados
"""

        CONTEXT_PATH.write_text(content, encoding="utf-8")
        logger.info(f"CONTEXT.md updated ({s['snap_count']:,} snapshots, {s['total_signals']} signals, {s['total_trades']} trades)")

    except Exception as e:
        logger.warning(f"context_updater failed: {e}")
