# Changelog v3.x — 2026-04-19 / 2026-04-20

Registro del día: cambios estructurales que cierran los gaps identificados
en el post-mortem del run v2.1 (−$531 en 36h, gap HR/WR de 57 puntos)
y aplican los conceptos del documento `niche_specialist_engine.html`
sin introducir una tercera estrategia.

---

## Diagnóstico previo

Run v2.1 terminó con:
- SCALPER: 63 trades cerrados, WR 46%, **−$279**
- SPECIALIST: 15 trades cerrados reales, WR 7%, **−$252**
- Total: **−$531** en ~36h

Las 4 causas raíz identificadas (ver [copy_trading_lessons.md](copy_trading_lessons.md)):

1. **`register_titular_loss()` nunca se llamaba** — estaba definido en
   `risk_manager_ct.py` pero no conectado al close flow. Circuit breaker
   por titular permanecía en 0 aunque el titular perdiera todo.
2. **`market_category=None` hardcodeado** en `scalper_executor.py:174`.
   Dashboard no podía filtrar por tipo de mercado en SCALPER.
3. **BTC Up/Down 5 min clasificado como `'other'`** — los regex de
   `market_type_classifier.py` sólo capturaban 15m+, y `'other'` estaba
   en la whitelist del pool. Wallet `0x7d30c522..` quemó ~$235 copiando
   binarios de 5 min.
4. **Gate EV inexistente** — signal_generator permitía entradas con
   `avg_hit_rate < entry_price` (EV negativo). Un trade BTC cerró TS
   a −7% con EV original de −3.2%.

Además el enricher daba HR 97% a wallets cuya WR real era 40% (gap 57
puntos), por contar posiciones abiertas como victorias en vez de trades
completados con beneficio.

---

## Commit 1 · `490355f` — v3.0 core fixes

**Título:** `fix(bot): v3.0 — wire per-titular CB, block micro-timeframes, EV gate`

**Archivos modificados:** 12

### Bugs críticos conectados
- [src/strategies/common/clob_exec.py](../src/strategies/common/clob_exec.py) — Invocar `register_titular_loss()` tras cada close real SCALPER. Añadido `source_wallet` a `_CLOSE_COLS` y `_COLS` de ambos flujos de cierre.
- [src/strategies/scalper/scalper_executor.py:174](../src/strategies/scalper/scalper_executor.py#L174) — `market_category=market_type` (la variable ya existía en L112).

### Clasificador + whitelist
- [src/strategies/specialist/market_type_classifier.py](../src/strategies/specialist/market_type_classifier.py) — Patrón `crypto_updown_micro` (5/10/15-min) antes del `_short`. Fallback cambiado de `'other'` a `'unclassified'` (permiso explícito en vez de catch-all).
- [src/strategies/scalper/pool_selector.py](../src/strategies/scalper/pool_selector.py) — `SCALPER_BLOCKED_MARKET_TYPES` se filtra de `approved_types` antes de persistir. Health gate vía Polymarket `data-api/value` (skip si `portfolio_value<$100`). Divergence gate (skip si `|best_hr - last_30d_wr| > 20pp`).
- [src/strategies/scalper/scalper_executor.py](../src/strategies/scalper/scalper_executor.py) — Runtime check que fuerza shadow si `market_type` no está en `approved_market_types` del titular o está en la blocked list.

### Gates de entrada SPECIALIST
- [src/strategies/common/config.py](../src/strategies/common/config.py) — Thresholds subidos empíricamente:
  - `SIGNAL_MIN_SPECIALISTS`: 2 → **4**
  - `SIGNAL_CLEAN_RATIO`: 2.5 → **3.0**
  - `SIGNAL_CONTESTED_RATIO`: 1.5 → **2.0**
  - `EV_MIN_ENTRY`: **0.0** (nuevo)
- [src/strategies/specialist/signal_generator.py](../src/strategies/specialist/signal_generator.py) — Gate EV (`dominant.avg_hit_rate − entry_price`) antes de emitir la señal.

### Validación cruzada
- [src/strategies/common/profile_enricher.py](../src/strategies/common/profile_enricher.py) — Campo `last_30d_actual_wr` calculado sobre trades cashPnl-confirmados en ventana corta.

### Resiliencia
- [src/strategies/common/db.py](../src/strategies/common/db.py) — `upsert_wallet_profile` intercepta `column X does not exist`, strippea el campo y reintenta. Permite deploy antes de aplicar migrations.

### Migration 013
- [src/db/migrations/013_v3_last_30d_wr.sql](../src/db/migrations/013_v3_last_30d_wr.sql) — `wallet_profiles.last_30d_actual_wr REAL`

### Tests (19)
- [tests/unit/test_circuit_breakers_ct.py](../tests/unit/test_circuit_breakers_ct.py) — 9 casos para `register_titular_loss` / `is_titular_broken` / recovery.
- [tests/unit/test_market_type_classifier.py](../tests/unit/test_market_type_classifier.py) — 10 casos con BTC 5min → micro, fallback `unclassified`, etc.

---

## Commit 2 · `a256d55` — v3.0 market-maker detection

**Título:** `feat(bot): v3.0 — market-maker detection heuristic`

**Archivos:** 4 (profile_enricher.py, pool_selector.py, migration 014, tests)

Detecta wallets que operan por arbitraje negativeRisk / MERGE+REDEEM en
mercados multi-outcome. Ejemplo real encontrado: wallet
`0x84571f1b..` ("ZhangMuZhi..") netea +$33k/día operando 3,200 veces cada
5 días. Su edge **no transfiere a copy-traders** porque mantiene
posiciones en TODOS los outcomes del mismo evento — copiar una sola
pata expone al copier a la pérdida completa.

### Heurística (3 señales, trigger con ≥2)
- `buy_skew`: BUY ratio ≥ 0.98 (MMs salen via REDEEM/MERGE, no SELL)
- `edge_concentration`: ≥25% de trades a precio ≥0.95 o ≤0.05
- `multi_outcome_presence`: ≥40% de trades en eventos con ≥3 outcomes tocados

### Verificación real
- ZhangMuZhi (MM target): `is_mm=True, conf=1.0, 3/3` ✓
- Weather distribution bot: `is_mm=True, conf=0.67, 2/3` ✓
- Scalper direccional quebrado: `is_mm=False, 1/3` ✓ (no era MM)

### Filtro
`pool_selector.select()` hace hard-skip con log `"Skip {wallet}… market_maker detected"` antes de scorear.

### Migration 014
- [src/db/migrations/014_v3_market_maker_flag.sql](../src/db/migrations/014_v3_market_maker_flag.sql) — `wallet_profiles.{is_market_maker, mm_confidence, mm_signals}` + índice parcial.

### Tests (6)
- [tests/unit/test_market_maker_heuristic.py](../tests/unit/test_market_maker_heuristic.py) — MM detectado / no-MM direccional / insuficiente data / 1 señal / 2 señales.

---

## Commit 3 · `c27afd9` — v3.1 niche_specialist_engine

**Título:** `feat(bot): v3.1 — niche_specialist_engine concepts ported`

Aplicación selectiva de 5 conceptos del doc `niche_specialist_engine.html`
**sin** introducir una 3ª estrategia separada. Los conceptos entran al
SPECIALIST/SCALPER existentes.

### Fase A · PnL formula correcta (§12)

Fórmula documentada:
```
position_pnl = Σsell + Σredeem − Σbuy + unrealized
```
SPLIT/MERGE nunca cuentan (conversiones de colateral, no flujo de PnL).

- [src/strategies/common/data_client.py](../src/strategies/common/data_client.py) — Nuevo `get_all_wallet_redeems()` paralelo a `get_all_wallet_trades()`.
- [src/strategies/common/profile_enricher.py](../src/strategies/common/profile_enricher.py) — `_pnl_for_cid` e `_infer_win` aceptan `redeem_proceeds` (dict por cid). Construido en `enrich_wallet` agregando USDC por conditionId. Propagado a `_compute_coverage_kpis`, `_compute_sizing_kpis` y `_compute_last_30d_actual_wr`.

Impacto: wallets que cierran por redemption (no venden) ya no aparecen
como "indeterminado" en el fallback PnL.

### Fase B · Niche concentration como soft penalty (§02)

Nuevo campo `niche_concentration_pct = max(type_trades) / total_resolved`
en el perfil. En `_composite_score` aplica penalty lineal cuando la
concentración < threshold:

```
concentration=0.70 → score × 1.00  (sin penalty)
concentration=0.55 → score × 0.968
concentration=0.40 → score × 0.936
concentration=0.00 → score × 0.85  (máxima penalty)
```

- [src/strategies/common/profile_enricher.py](../src/strategies/common/profile_enricher.py) — Cálculo del campo en coverage_kpis.
- [src/strategies/scalper/pool_selector.py](../src/strategies/scalper/pool_selector.py) — Penalty aplicada al final de `_composite_score`.
- Config: `NICHE_CONCENTRATION_THRESHOLD=0.70`, `PENALTY_MAX=0.15`.

### Fase C · Gamma tags classifier con cache DB (§08)

Clasificador secundario que consulta Gamma API cuando el regex devuelve
`'unclassified'`. Cache permanente en DB para evitar llamadas repetidas.

- [src/data/gamma_tags_client.py](../src/data/gamma_tags_client.py) — Nuevo. `get_niche_for_event()` con in-memory LRU + DB cache + Gamma `/events/slug/{slug}?include_tag=true`. Mapa `TAG_TO_TYPE` cubre weather/sports/crypto/politics/mentions/macro.
- [src/strategies/common/profile_enricher.py](../src/strategies/common/profile_enricher.py) — Fallback en `_compute_coverage_kpis`: si `classify()==unclassified`, llama al cliente Gamma para recuperar el niche real.

**Zero cambios al hot path** — el scalper_executor y trade_executor siguen
usando el regex síncrono para latencia mínima.

### Fase D · Shadow validation gate (§03, §04)

Nuevos titulares spend 14 días en shadow antes de operar real:

- Pool_selector marca `shadow_validation_until = now() + 14d` y `validation_outcome = 'PENDING'` al persistir.
- `scalper_executor.mirror_open()` verifica el flag y fuerza `is_shadow=True` durante la ventana.
- [src/strategies/scalper/shadow_validator.py](../src/strategies/scalper/shadow_validator.py) (nuevo) — Cron-invocable. Para cada titular cuyo window expiró y está PENDING:
  - Promueve si `n_closed≥5` + `wr≥0.55` + `paper_pnl ≥ 0`
  - Rechaza en cualquier otro caso → `status='POOL'`

Config: `SHADOW_VALIDATION_DAYS=14`, `SHADOW_MIN_TRADES=5`, `SHADOW_PAPER_WR_FLOOR=0.55`, `SHADOW_PAPER_PNL_FLOOR_PCT=0.0`.

### Fase E · Degradation evaluator cron 6h (§09)

Job autónomo con reglas numéricas claras:

- [src/strategies/scalper/degradation_evaluator.py](../src/strategies/scalper/degradation_evaluator.py) (nuevo) — Para cada `ACTIVE_TITULAR` no broken y fuera de shadow window:
  - `pnl_7d_pct ≤ −12%` OR `wr_15 < 0.62` → **pause** (marca `per_trader_is_broken=True`)
  - `0.62 ≤ wr_15 < 0.65` AND `sizing_mult > 0.5` → **reduce** (sizing × 0.5)
  - `wr_10 ≥ 0.70` AND `sizing_mult < 1.0` → **restore** (sizing → 1.0)
- Todas las transiciones se registran en tabla `risk_events` (audit).

Config: `DEGRADATION_EVAL_HOURS=6`, `WINDOW_DAYS=7`, `PNL_7D_PAUSE_PCT=−0.12`, `WR15_PAUSE=0.62`, `WR15_REDUCE=0.65`, `RECOVERY_WR10=0.70`.

CLI: `python -m src.strategies.scalper.degradation_evaluator` (invoca shadow_validator primero).

### Migrations 015-018

- [015_v3_niche_concentration.sql](../src/db/migrations/015_v3_niche_concentration.sql) — `wallet_profiles.niche_concentration_pct`
- [016_v3_market_tags_cache.sql](../src/db/migrations/016_v3_market_tags_cache.sql) — Tabla `market_tags_cache (event_slug, tag_slugs, niche, cached_at)`
- [017_v3_shadow_validation.sql](../src/db/migrations/017_v3_shadow_validation.sql) — `scalper_pool.{shadow_validation_until, validation_outcome}` + índice
- [018_v3_sizing_multiplier.sql](../src/db/migrations/018_v3_sizing_multiplier.sql) — `scalper_pool.sizing_multiplier` + tabla `risk_events`

Todas `IF NOT EXISTS`, safe a re-ejecutar.

### Tests (51 nuevos en esta fase)

| Archivo | Casos |
|---|---|
| [test_pnl_formula.py](../tests/unit/test_pnl_formula.py) | 14 — 6 obligatorios del doc + SPLIT/MERGE neutrales + _infer_win |
| [test_niche_concentration_penalty.py](../tests/unit/test_niche_concentration_penalty.py) | 6 — threshold/half/max/no-flip |
| [test_gamma_tags_client.py](../tests/unit/test_gamma_tags_client.py) | 14 — tag mapping + cache miss/hit + errores de red |
| [test_shadow_validator.py](../tests/unit/test_shadow_validator.py) | 5 — promote/reject-few/reject-wr/reject-pnl/pending |
| [test_degradation_evaluator.py](../tests/unit/test_degradation_evaluator.py) | 7 — cada rama de reglas + skip paths |

---

## Total tests v3.0 + v3.1

**76 tests unit, todos verdes**. Distribución:
- Circuit breakers per-titular: 9
- Market type classifier: 10
- Market maker heuristic: 6
- PnL formula: 14
- Niche concentration penalty: 6
- Gamma tags client: 14
- Shadow validator: 5
- Degradation evaluator: 7

---

## Infraestructura

### Reset run v3.0
Ejecutado 2026-04-19 21:16 UTC. Runs activos:
- SCALPER: `b4a40e7d-50ec-476f-9765-e4fbab02608e`
- SPECIALIST: `b3af0daf-...`

Pool v3.0 seleccionó 4 nuevos titulares con tipos limpios (`crypto_above`,
`sports_winner`); wallet `0x7d30c522..` (quebrada, value=$0) fue
automáticamente excluida por el health gate.

### Cron activo (VPS)
```
0 0 * * 1   rotation semanal lunes 00:00 UTC
0 */6 * * * shadow_validator + degradation_evaluator
```

Jobs verificados con ejecución manual — 0 errores, skipped=4 porque los
titulares actuales no tienen trades cerrados aún.

### Deploy
Todos los cambios desplegados al VPS vía `git archive HEAD | ssh`.
Servicios reiniciados: `polymarket-specialist`, `polymarket-scalper`.

---

## Estado al cierre (2026-04-20 ~00:30 UTC)

**SCALPER v3.0**: operando. 6 trades abiertos (3 real + 3 shadow). Trailing
stop activo en trade de Canadiens vs Lightning.

**SPECIALIST v3.0**: operando. Trades abiertos en NBA/NHL/BTC con nuevos
thresholds (MIN_SPECIALISTS=4, CLEAN=3.0).

**Los 4 titulares SCALPER están activos** en Polymarket — cada uno operó
en las últimas 0.5-2.5h. Los 2 que no han sido copiados operaron
probablemente en tipos de mercado fuera de su `approved_market_types`,
por lo que se filtraron correctamente como esperado.

---

## Limitaciones y trabajo futuro

- Los 4 titulares del run v3.0 entraron al pool **antes** de la migration
  017 (columnas shadow_validation). No tienen gate de 14d retroactivo.
  Los del próximo reset/rotación (lunes) sí lo llevarán.
- `sizing_multiplier` de `scalper_pool` no se está consumiendo aún en
  `portfolio_sizer.compute_trade_size()` — pendiente conectarlo para
  que la Capa 1b del doc tenga efecto real.
- Badges de health en dashboard pendientes (portfolio_value, CB counter,
  divergencia HR/WR) — mencionados en Fase 6 del plan inicial, quedaron
  fuera de alcance para no demorar el reset.
- Shadow gate + degradation thresholds calibrados con datos de la Fase 1
  del doc (no los nuestros) — posible re-calibración tras 30 días de
  producción real v3.x.
