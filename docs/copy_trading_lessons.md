# Lecciones aprendidas en sistemas de copy-trading algorítmico

> Documento de referencia para futuros desarrollos. Basado en errores reales de producción.  
> Los ejemplos son concretos pero los principios son universales.

---

## 1. Problemas de datos — Lo que no validas, te destruye

### Error: confiar en una única fuente de verdad

El sistema calculó una HR (hit rate) del 97% para un trader. La WR real en producción fue del 40%. Diferencia: **57 puntos porcentuales**.

El enriquecedor contaba victorias a nivel de *posición* (tiene tokens) en lugar de a nivel de *trade completado* (compró y vendió con ganancia). Son métricas completamente distintas que producen el mismo nombre de campo.

**Regla:** Toda métrica de rendimiento crítica debe calcularse por al menos dos métodos independientes y compararse. Si divergen más de un 10%, la métrica es sospechosa y no debe usarse para tomar decisiones reales.

**Regla:** Nunca usar datos de producción real hasta haber validado que la métrica es fiel. Primero shadow (paper trading), luego real con tamaño mínimo, luego escalar.

---

### Error: métricas estáticas para traders dinámicos

El perfil de un trader se captura en un momento T y se usa indefinidamente. Un trader puede haber sido excelente hace 30 días y estar quebrado hoy.

En producción: una wallet con `composite_score: 0.893` y presencia en el pool tenía `portfolio_value: $0` en Polymarket. El sistema seguía copiándole.

**Regla:** Cualquier fuente que se copia debe tener una señal de "salud actual" verificada periódicamente (p.ej. cada ciclo de run). Una cartera vaciada, inactiva o con racha de pérdidas recientes debe suspenderse automáticamente, no esperar a que el gestor lo detecte manualmente.

**Regla:** Separar métricas históricas (lo que fue) de señales operativas actuales (lo que está haciendo ahora). El perfil histórico es para selección; la salud actual es para ejecución.

---

### Error: clasificación catch-all en tipos de mercado

Existía un bucket `'other'` en la clasificación de mercados que actuaba como papelera: cualquier mercado no reconocido caía ahí y se copiaba igualmente.

Los mercados de ventanas de 5 minutos ("¿subirá BTC en los próximos 5 minutos?") son pura aleatoriedad para cualquier estrategia de copy-trading — ningún titular tiene edge real en ese horizonte. Cayeron en `'other'` y se ejecutaron 45 veces.

**Regla:** El bucket por defecto debe ser **deniega**, no permite. Si un mercado no cae en una categoría explícitamente aprobada, no se opera. El permiso debe ser explícito; el bloqueo debe ser implícito.

**Regla:** Cualquier mercado con horizonte temporal inferior a 30 minutos debe estar bloqueado por defecto en estrategias de copy-trading. La velocidad del mercado supera la latencia del sistema.

---

## 2. Problemas de diseño — Arquitectura que falla silenciosamente

### Error: circuit breakers definidos pero no ejecutados

El schema tenía campos `per_trader_consecutive_losses` y `per_trader_is_broken`. En producción, ambos permanecían en `0` y `false` con pérdidas masivas acumuladas. El código que debía incrementarlos no estaba conectado al flujo de ejecución.

**Regla:** Los mecanismos de protección (circuit breakers, stop-loss, límites de pérdida) deben probarse explícitamente en tests de integración antes de ir a producción. No basta con que el campo exista en la base de datos.

**Regla:** Todo mecanismo de protección debe tener logging explícito cuando se activa ("circuit breaker activado para wallet X tras N pérdidas consecutivas"). Si nunca ves ese log en producción, el mecanismo no funciona.

---

### Error: shadow trading sin gate hacia producción

El sistema generaba cientos de shadow trades (paper trading) correctamente. Pero estos shadow trades no bloqueaban ni condicionaban la apertura de trades reales. Eran un log pasivo sin efecto alguno.

**Regla:** Shadow trades deben tener un rol activo: antes de operar real con una nueva estrategia o señal, debe haber un periodo de shadow con resultado positivo (p.ej. WR > X% en N trades mínimos). Si el shadow pierde, no se activa el real.

**Regla:** Shadow y real nunca deben correr simultáneamente sin que haya una decisión consciente de que el shadow validó la estrategia.

---

### Error: señal de calidad no correlacionada con resultado

El sistema diferenciaba entre señales CLEAN y CONTESTED asumiendo que CLEAN predice mejor resultado.

Resultados reales: CLEAN WR = 11%, CONTESTED WR = 0%. La distinción no aportó valor predictivo.

El número de especialistas tampoco fue predictivo: 11 especialistas → pérdida, 5 especialistas → el único ganador del periodo.

**Regla:** Toda señal de calidad debe validarse estadísticamente contra resultados reales antes de usarla para dimensionar posiciones o filtrar trades. Una etiqueta CLEAN/CONTESTED sin backtest de correlación es folklore, no edge.

**Regla:** Cuando una señal clasificadora no muestra correlación con el resultado en producción después de suficientes trades, debe eliminarse o reconstruirse. Mantenerla activa tiene coste de oportunidad y complejidad.

---

### Error: tamaño de posición sin gradiente de convicción

Todas las posiciones se abrían con el mismo tamaño independientemente de: número de especialistas, HR histórica, calidad de señal, o volatilidad del mercado.

Si una señal tiene edge, hay que apostar más cuando el edge es mayor y menos cuando es menor (Kelly criterion simplificado). Tamaño plano es subóptimo en ambos casos.

**Regla:** El tamaño de posición debe ser función del nivel de convicción. Mínimo dos niveles (normal / alta convicción). Idealmente calculado como fracción del capital en función de la ventaja estimada.

---

### Error: seguir a titulares sin verificar su propio edge actual

La selección de titulares a copiar se basó en métricas enriquecidas, no en su rendimiento reciente verificable. En producción, los titulares copiados también estaban perdiendo (uno con cartera a cero, otro con -$3k no realizados en una sola posición).

**Regla:** Antes de copiar a alguien, verificar su estado actual en la plataforma subyacente. Si tienen pérdidas no realizadas grandes o cartera mermada, no son una señal fiable en ese momento aunque su perfil histórico sea bueno.

**Regla:** No existe "perfil permanente". Un trader con buen historial puede estar en una mala racha o haber cambiado de estrategia. El perfil histórico da probabilidad de base; el estado actual la ajusta.

---

## 3. Problemas de estrategia — Operar mercados donde no hay edge

### Error: operar mercados demasiado eficientes o ruidosos

Los mercados deportivos nocturnos americanos (NBA, NHL) con precios de entrada en rango 0.3-0.7 son mercados líquidos con mucha participación humana y modelos estadísticos sofisticados. El edge de copy-trading aquí es mínimo.

Los mercados de crypto 5-minutos son ruido puro a escala de un copy-trading bot.

**Regla:** Identificar en qué tipo de mercados tiene edge la fuente antes de copiarla. No todos los mercados en los que opera un trader ganador son mercados donde él tiene edge — puede estar diversificando ruido.

**Regla:** Los mercados donde el bot tiene sistemáticamente WR < 50% deben bloquearse aunque el titular tenga historial positivo en ellos. La latencia, el spread y la selección adversa consumen el edge del titular antes de que llegue al copiador.

---

### Error: entrar cuando el EV ya es negativo

En el ejemplo BTC: HR especialistas = 81%, precio de entrada = 84.2%. EV = -3.2%. El sistema entró igualmente porque la señal era CLEAN con 11 especialistas.

Un EV negativo significa que el mercado ya ha descontado la información que tienen los especialistas (o más). Entrar en ese punto es comprar caro lo que ya todo el mundo sabe.

**Regla:** EV positivo debe ser condición necesaria para entrar, no opcional. Si `avg_hit_rate < entry_price`, no operar independientemente del número de especialistas o calidad de señal.

**Regla:** El EV captura el estado del mercado en el momento de entrada. Una señal buena con EV negativo es una señal tardía — la información ya está en el precio.

---

### Error: stop-loss como principal fuente de pérdida

Cuando el stop-loss genera el 95% de las pérdidas y el trailing-stop apenas genera pérdidas, el problema no es el SL en sí — es que se está entrando en trades que inmediatamente van en dirección contraria.

Los trailing-stops en este caso sí funcionan: permiten cortar pérdidas pequeñas. Los SL duros indican entradas incorrectas que el mercado rechaza con fuerza.

**Regla:** Si el SL se activa en >50% de los trades cerrados, el problema es la señal de entrada, no los niveles de SL. Revisar la lógica de señal antes de ajustar SL.

**Regla:** Monitorear la distribución de close_reasons periódicamente. La distribución ideal es: TP >> TRAILING_STOP > MARKET_RESOLVED >> SL. Cualquier otra distribución indica un problema de estrategia.

---

## 4. Problemas de operaciones — Lo que no se mide, no se gestiona

### Error: capital_allocated_usd sin actualizar

El campo `capital_allocated_usd` permanecía en 0 para todas las wallets del pool. Sin saber cuánto capital real está expuesto por wallet, es imposible gestionar el riesgo del portfolio.

**Regla:** El capital en riesgo por fuente y por estrategia debe ser un dato de primera clase, actualizado en tiempo real. Sin este dato no se puede hacer gestión de riesgo real.

---

### Error: categoría de mercado sin taggear en trades

`market_category` aparecía como `UNKNOWN` en todos los trades del SCALPER. Sin esa dimensión, no se puede analizar qué categoría funciona y cuál destruye valor.

**Regla:** Todos los atributos de clasificación deben estar presentes en el trade en el momento de la apertura. Un trade sin categoría es un dato ciego — no permite aprender de él.

---

### Error: ausencia de alertas en tiempo real

Los problemas (wallet quemada, circuit breaker inactivo, HR vs WR divergente) solo se detectaron en una revisión manual. No había ningún mecanismo que alertara al operador cuando:
- Una wallet del pool pierde N trades consecutivos
- La WR real en ventana de 24h cae por debajo de X%
- El total de pérdidas del run supera un umbral

**Regla:** Definir alertas operativas desde el día 1, antes de ir a producción. Mínimo: pérdida diaria máxima, pérdidas consecutivas por fuente, divergencia HR-WR acumulada.

---

## 5. Buenas prácticas generales para sistemas de copy-trading

### Principio de desconfianza por defecto
Asumir que toda fuente de datos puede estar equivocada. Validar métricas críticas por múltiples caminos. Si solo tienes una forma de medir algo importante, no lo has medido — tienes una suposición.

### Principio de gradualidad
Nueva estrategia → shadow primero → real con tamaño mínimo → escalar solo si los resultados reales confirman el shadow. Nunca saltarse pasos porque "los datos parecen buenos".

### Principio de separación de capas
- **Capa de datos**: calidad, frescura, validación cruzada
- **Capa de señal**: generación, filtrado, calidad estimada
- **Capa de ejecución**: sizing, timing, gestión de posición
- **Capa de protección**: circuit breakers, stop-loss, límites de exposición
- **Capa de observabilidad**: métricas, alertas, logs

Cada capa debe poder probarse de forma independiente. Un bug en la capa de protección no debe poder ocultarse detrás de un aparente buen funcionamiento de la capa de señal.

### Principio de permiso explícito
Todo lo que no está explícitamente permitido, está bloqueado. Aplica a: tipos de mercado, wallets a copiar, rangos de precio de entrada, horarios de operación. El defecto siempre es "no operar".

### Principio de reversibilidad
Antes de deployar cualquier cambio en producción real, asegurarse de que hay un mecanismo de rollback: poder revertir a la configuración anterior en menos de 5 minutos sin perder datos.

### Principio de observabilidad antes que optimización
No optimizar lo que no se puede observar. Antes de mejorar una métrica, asegurarse de que se puede medir con fiabilidad. El ciclo correcto es: medir → entender → cambiar → medir de nuevo.

---

## 6. Checklist pre-producción para nuevas estrategias

- [ ] ¿Las métricas de selección de fuentes han sido validadas contra resultados reales (no solo calculadas)?
- [ ] ¿Existe un periodo de shadow trading con umbral mínimo de trades y WR para activar el real?
- [ ] ¿Los circuit breakers (por wallet, por estrategia, por día) tienen tests automáticos?
- [ ] ¿El bucket por defecto de tipos de mercado es "bloquear"?
- [ ] ¿Hay alertas activas para pérdida diaria máxima y pérdidas consecutivas?
- [ ] ¿`capital_allocated_usd` se actualiza en tiempo real?
- [ ] ¿Todos los trades se guardan con `market_category` poblado?
- [ ] ¿El EV es una condición de entrada, no solo un campo informativo?
- [ ] ¿Se verifica la salud actual de las fuentes antes de cada ciclo de copia?
- [ ] ¿La distribución de `close_reason` se monitorea periódicamente?

---

*Última actualización: abril 2026*
