"use client";

import { useCallback, useState } from "react";
import { useAutoRefresh } from "@/lib/hooks";

type Snapshot = {
  snapshot_at: string;
  content: {
    generated_at: number;
    specialist_config: Record<string, unknown>;
    scalper_config: Record<string, unknown>;
    risk_config: Record<string, unknown>;
    db_state: Record<string, unknown>;
    modules: Array<{ name: string; desc: string }>;
    services: Array<{ name: string; desc: string }>;
    paper_mode: boolean;
  };
  version: string | null;
};

export default function RoadmapPage() {
  const fetcher = useCallback(
    () => fetch("/api/roadmap").then((r) => r.json()),
    [],
  );
  const { data } = useAutoRefresh<{ snapshot: Snapshot | null }>(fetcher, 300000);
  const snapshot = data?.snapshot?.content;
  const snapshotAt = data?.snapshot?.snapshot_at;

  return (
    <div style={{ padding: 24, maxWidth: 900, lineHeight: 1.7 }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>Roadmap</h1>
      <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 24 }}>
        Referencia completa de la aplicacion — actualizada diariamente
        {snapshotAt && (
          <span style={{ marginLeft: 8, fontStyle: "italic" }}>
            (ultima actualizacion: {new Date(snapshotAt).toLocaleString("es-ES", { dateStyle: "long", timeStyle: "short" })})
          </span>
        )}
      </p>

      {/* ── 1. Vision general ──────────────────────────────── */}
      <Section title="1. Vision general y objetivos" defaultOpen>
        <p>
          <b>Polymarket Copytrading Bot</b> es un sistema de copy-trading automatizado
          para <a href="https://polymarket.com" target="_blank" rel="noopener noreferrer" style={{ color: "var(--blue)" }}>Polymarket</a>,
          la plataforma lider de mercados de prediccion. El bot detecta traders con
          rendimiento demostrado y copia sus operaciones de forma automatica.
        </p>
        <p style={{ marginTop: 8 }}>
          <b>Tesis de inversion:</b> Los mercados de prediccion tienen asimetria de informacion.
          Los traders con historial probado de acierto en tipos concretos de mercado
          (crypto, deportes, politica) tienen una ventaja repetible. Copiar selectivamente
          sus operaciones en sus verticales de mayor rendimiento captura esa ventaja
          mientras la diversificacion entre multiples traders reduce el riesgo.
        </p>
        <p style={{ marginTop: 8 }}>
          <b>Dos estrategias complementarias:</b>
        </p>
        <ul style={{ paddingLeft: 20, marginTop: 4 }}>
          <li><b>Specialist Edge</b> — detecta consenso entre especialistas sobre mercados concretos</li>
          <li><b>Scalper V2</b> — copia trades de traders top en sus verticales de mayor hit rate</li>
        </ul>
        <p style={{ marginTop: 8 }}>
          <b>Modo actual:</b> {snapshot?.paper_mode !== false ? "Paper trading (simulado, sin dinero real)" : "Live trading"}
        </p>
      </Section>

      {/* ── 2. Arquitectura ────────────────────────────────── */}
      <Section title="2. Arquitectura general">
        <pre style={{
          background: "var(--bg-secondary)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 16,
          fontSize: 12,
          lineHeight: 1.6,
          overflow: "auto",
        }}>
{`Polymarket APIs (CLOB + Data + Gamma)
          |
          v
  Profile Enricher (daemon, 90s)
  Analiza wallets con 45+ KPIs
          |
          v
  wallet_profiles (BD Supabase)
     |                    |
     v                    v
SPECIALIST            SCALPER V2
Signal Detection      Pool Selection (composite score)
     |                    |
Slot Orchestrator     Copy Monitor (filtrado por tipo)
     |                    |
Paper Trades          Paper Trades
     |                    |
     +--------+-----------+
              |
         Dashboard (Next.js)
         Visualizacion + Config`}
        </pre>
        <p style={{ marginTop: 12 }}>
          <b>Stack:</b> Backend Python 3.11, Dashboard Next.js 14, BD Supabase (PostgreSQL),
          Deploy via systemd en servidor Linux.
        </p>
      </Section>

      {/* ── 3. Specialist Edge ──────────────────────────────── */}
      <Section title="3. Estrategia Specialist Edge">
        <p>
          <b>Objetivo:</b> Detectar traders especializados en tipos concretos de mercado
          (ej: crypto above/below, sports winners) y abrir posiciones cuando multiples
          especialistas coinciden en el mismo lado de un mercado (senal de consenso).
        </p>

        <h4 style={{ marginTop: 12, marginBottom: 4 }}>Como funciona:</h4>
        <ol style={{ paddingLeft: 20 }}>
          <li>El clasificador de mercados categoriza cada mercado en ~20 tipos estructurales
          (crypto_above, sports_winner, politics_election, econ_fed_rates, etc.)</li>
          <li>El sistema analiza las posiciones de miles de wallets y detecta cuales
          tienen hit rate superior en tipos concretos = "especialistas"</li>
          <li>Cuando 2+ especialistas compran el mismo lado de un mercado → senal CLEAN</li>
          <li>El slot orchestrator asigna la operacion a un universo con slots disponibles</li>
          <li>Trailing stop protege ganancias (+8% activacion, 15% trail bajo HWM)</li>
          <li>Los mercados se resuelven automaticamente al cierre via CLOB API</li>
        </ol>

        <ConfigValues
          title="Parametros actuales"
          values={snapshot?.specialist_config}
          labels={{
            "initial_capital": "Capital inicial",
            "consecutive_loss_limit": "Limite perdidas consecutivas (CB)",
            "signal_clean_ratio": "Ratio senal CLEAN (for/against)",
            "signal_min_specialists": "Min especialistas para senal",
          }}
        />

        {snapshot?.specialist_config?.universes && (
          <div style={{ marginTop: 8 }}>
            <b style={{ fontSize: 13 }}>Universos:</b>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4, fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  <th style={{ textAlign: "left", padding: 4 }}>Universo</th>
                  <th style={{ textAlign: "right", padding: 4 }}>Capital</th>
                  <th style={{ textAlign: "right", padding: 4 }}>Slots</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(snapshot.specialist_config.universes as Record<string, Record<string, unknown>>).map(([name, u]) => (
                  <tr key={name} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: 4 }}>{name}</td>
                    <td style={{ textAlign: "right", padding: 4 }}>{((u.capital_pct as number) * 100).toFixed(0)}%</td>
                    <td style={{ textAlign: "right", padding: 4 }}>{u.max_slots as number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* ── 4. Scalper V2 ──────────────────────────────────── */}
      <Section title="4. Estrategia Scalper V2">
        <p>
          <b>Objetivo:</b> Copiar operaciones de traders con rendimiento demostrado,
          pero SOLO en los tipos de mercado donde ese trader destaca. No se copia
          todo — solo las verticales con edge probado.
        </p>

        <h4 style={{ marginTop: 12, marginBottom: 4 }}>Como funciona:</h4>
        <ol style={{ paddingLeft: 20 }}>
          <li><b>Seleccion:</b> Se consulta la BD de perfiles enriquecidos (wallet_profiles).
          Para cada wallet se calcula un composite score por tipo de mercado ponderando
          hit rate (30%), profit factor (15%), Sharpe por tipo (15%), estabilidad (10%),
          momentum (10%), trades (10%), confianza (5%) y prioridad (5%).</li>
          <li><b>4 titulares:</b> Se seleccionan los 4 mejores perfiles maximizando
          diversidad de tipos. Cada uno recibe el 25% del capital (autocompounding).</li>
          <li><b>Filtrado:</b> Cuando un titular opera, se clasifica el tipo de mercado.
          Si esta en su lista de tipos aprobados → se copia. Si no → se ignora.</li>
          <li><b>Sizing:</b> 15% de la asignacion del titular por trade (no del trade del trader).
          Autocompounding: si el portfolio sube, los trades crecen proporcionalmente.</li>
          <li><b>Bonus:</b> Un titular con 3+ wins consecutivos recibe +5% extra (30% total).</li>
          <li><b>Riesgo individual:</b> Cada titular tiene un CB adaptativo basado en su HR
          (HR=0.65 → 4 perdidas seguidas max). Solo se pausa a ESE titular.</li>
          <li><b>Riesgo global:</b> 6 perdidas totales cross-titular → pausa general.</li>
          <li><b>Trailing stop:</b> Misma logica que Specialist (+8% / 15% trail).</li>
          <li><b>Rotacion:</b> Health-check cada 72h. Solo rota si hay degradacion real
          (score bajo 0.40, perdidas consecutivas, inactividad, tendencia negativa).</li>
          <li><b>Cooldown:</b> Titular retirado recibe 30/60/90 dias de cooldown
          (escalacion por reincidencia).</li>
        </ol>

        <ConfigValues
          title="Parametros actuales"
          values={snapshot?.scalper_config}
          labels={{
            "active_wallets": "Titulares activos",
            "min_hit_rate": "HR minimo por tipo",
            "min_trade_count": "Trades minimos por tipo",
            "trade_pct": "% asignacion por trade",
            "max_trade_pct": "% maximo por trade",
            "bonus_pct": "Bonus por racha (+%)",
            "max_open_positions": "Max posiciones abiertas (global)",
            "health_check_hours": "Health check cada (horas)",
            "cooldown_days_base": "Cooldown base (dias)",
            "consecutive_loss_limit": "CB global (perdidas)",
            "priority_boost": "Boost tipos prioritarios (x)",
          }}
        />
      </Section>

      {/* ── 5. Profile Enricher ────────────────────────────── */}
      <Section title="5. Profile Enricher">
        <p>
          Daemon que enriquece perfiles de wallets con 45+ KPIs agrupados en bloques:
          cobertura por tipo/universo, sizing y conviccion, portfolio, temporales y momentum.
          Tambien clasifica cada wallet en 8 arquetipos estilo Hearthstone
          (EDGE_HUNTER, HODLER, SPECIALIST, GENERALIST, WHALE, SCALPER_PROFILE, BOT, MOMENTUM_CHASER)
          con 4 niveles de rareza (LEGENDARY, EPIC, RARE, COMMON).
        </p>
        <p style={{ marginTop: 8 }}>
          <b>Frecuencia:</b> Cada 90 segundos, procesa 3 wallets.
          <br />
          <b>Fuentes:</b> Polymarket Data API (trades) + Positions API (holdings actuales).
          <br />
          <b>Uso:</b> Alimenta la seleccion del Scalper V2 y la pagina /wallets del dashboard.
        </p>
      </Section>

      {/* ── 6. Gestion de riesgo ───────────────────────────── */}
      <Section title="6. Gestion de riesgo global">
        <ConfigValues
          title="Limites de riesgo"
          values={snapshot?.risk_config}
          labels={{
            "max_drawdown_pct": "Drawdown maximo desde ATH",
            "max_per_trade_pct": "Maximo por trade (% capital)",
            "timeout_days": "Timeout de posiciones (dias)",
            "min_liquidity_24h": "Liquidez minima 24h ($)",
            "max_slippage": "Slippage maximo",
          }}
        />
        <div style={{ marginTop: 12 }}>
          <b>Circuit breakers:</b>
          <ul style={{ paddingLeft: 20, marginTop: 4 }}>
            <li>Scalper global: {snapshot?.scalper_config ? String((snapshot.scalper_config as Record<string, unknown>).consecutive_loss_limit) : "6"} perdidas consecutivas → pausa + revision manual</li>
            <li>Scalper individual: adaptativo al HR del trader (2-5 perdidas segun perfil)</li>
            <li>Specialist: {snapshot?.specialist_config ? String((snapshot.specialist_config as Record<string, unknown>).consecutive_loss_limit) : "5"} perdidas consecutivas</li>
            <li>Drawdown: cierre automatico si supera el {snapshot?.risk_config ? String(Number((snapshot.risk_config as Record<string, unknown>).max_drawdown_pct) * 100) : "30"}% desde ATH</li>
          </ul>
        </div>
      </Section>

      {/* ── 7. Dashboard ───────────────────────────────────── */}
      <Section title="7. Dashboard">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <tbody>
            {[
              ["Dashboard (/)", "Vista principal con resumen de portfolio, P&L y posiciones"],
              ["Analytics (/analytics)", "Graficos de rendimiento historico"],
              ["Wallets (/wallets)", "Perfiles enriquecidos con arquetipos y cromos TCG"],
              ["Specialist Edge (/specialist)", "Universos, slots, especialistas detectados"],
              ["Scalper Pool (/rotation)", "Historial de rotaciones y pool de candidatos (V1)"],
              ["Scalper V2 (/scalper)", "Titulares activos, balance, config editable"],
              ["Shadow (/shadow)", "Comparativa trades reales vs shadow (sin stops)"],
              ["Roadmap (/roadmap)", "Esta pagina — referencia completa del sistema"],
              ["Services (/services)", "Estado de los daemons systemd"],
              ["Settings (/settings)", "Configuracion del dashboard"],
            ].map(([page, desc]) => (
              <tr key={page} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", fontWeight: 600, whiteSpace: "nowrap" }}>{page}</td>
                <td style={{ padding: "6px 8px", color: "var(--text-secondary)" }}>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* ── 8. Modulos ─────────────────────────────────────── */}
      <Section title="8. Modulos y servicios">
        {snapshot?.modules && (
          <>
            <b style={{ fontSize: 13 }}>Modulos Python:</b>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4, fontSize: 12 }}>
              <tbody>
                {snapshot.modules.map((m) => (
                  <tr key={m.name} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "4px 8px", fontFamily: "monospace", whiteSpace: "nowrap" }}>{m.name}</td>
                    <td style={{ padding: "4px 8px", color: "var(--text-secondary)" }}>{m.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {snapshot?.services && (
          <div style={{ marginTop: 12 }}>
            <b style={{ fontSize: 13 }}>Servicios systemd:</b>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4, fontSize: 12 }}>
              <tbody>
                {snapshot.services.map((s) => (
                  <tr key={s.name} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "4px 8px", fontFamily: "monospace", whiteSpace: "nowrap" }}>{s.name}</td>
                    <td style={{ padding: "4px 8px", color: "var(--text-secondary)" }}>{s.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* ── Estado actual de BD ──────────────────────────── */}
      {snapshot?.db_state && (
        <Section title="9. Estado actual">
          <DbStatePanel state={snapshot.db_state} />
        </Section>
      )}
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────── */

function Section({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{
      marginBottom: 16,
      border: "1px solid var(--border)",
      borderRadius: 8,
      overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          padding: "12px 16px",
          background: "var(--bg-secondary)",
          border: "none",
          textAlign: "left",
          cursor: "pointer",
          fontSize: 15,
          fontWeight: 700,
          color: "var(--text-primary)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        {title}
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          {open ? "[-]" : "[+]"}
        </span>
      </button>
      {open && (
        <div style={{ padding: "12px 16px", fontSize: 13 }}>
          {children}
        </div>
      )}
    </div>
  );
}

function ConfigValues({
  title,
  values,
  labels,
}: {
  title: string;
  values: Record<string, unknown> | undefined;
  labels: Record<string, string>;
}) {
  if (!values) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <b style={{ fontSize: 13 }}>{title}:</b>
      <table style={{ borderCollapse: "collapse", marginTop: 4, fontSize: 12 }}>
        <tbody>
          {Object.entries(labels).map(([key, label]) => {
            const val = values[key];
            const display =
              typeof val === "number"
                ? val < 1 && val > 0
                  ? `${(val * 100).toFixed(1)}%`
                  : String(val)
                : val === undefined || val === null
                  ? "—"
                  : String(val);
            return (
              <tr key={key}>
                <td style={{ padding: "2px 12px 2px 0", color: "var(--text-secondary)" }}>{label}</td>
                <td style={{ padding: "2px 0", fontWeight: 600 }}>{display}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DbStatePanel({ state }: { state: Record<string, unknown> }) {
  const sp = state.specialist_portfolio as Record<string, unknown> | null;
  const sc = state.scalper_portfolio as Record<string, unknown> | null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <div style={{ background: "var(--bg-secondary)", borderRadius: 6, padding: 12 }}>
        <b>Specialist Portfolio</b>
        {sp ? (
          <div style={{ marginTop: 4, fontSize: 12, lineHeight: 1.8 }}>
            <div>Capital: ${Number(sp.current_capital).toFixed(2)}</div>
            <div>P&L: ${Number(sp.total_pnl).toFixed(2)}</div>
            <div>Trades: {String(sp.total_trades)}</div>
            <div>Win Rate: {(Number(sp.win_rate) * 100).toFixed(1)}%</div>
            <div>CB: {sp.is_circuit_broken ? "ACTIVE" : "OK"}</div>
          </div>
        ) : (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-secondary)" }}>Sin datos</div>
        )}
      </div>
      <div style={{ background: "var(--bg-secondary)", borderRadius: 6, padding: 12 }}>
        <b>Scalper Portfolio</b>
        {sc ? (
          <div style={{ marginTop: 4, fontSize: 12, lineHeight: 1.8 }}>
            <div>Capital: ${Number(sc.current_capital).toFixed(2)}</div>
            <div>P&L: ${Number(sc.total_pnl).toFixed(2)}</div>
            <div>Trades: {String(sc.total_trades)}</div>
            <div>Win Rate: {(Number(sc.win_rate) * 100).toFixed(1)}%</div>
            <div>CB: {sc.is_circuit_broken ? "ACTIVE" : "OK"}</div>
          </div>
        ) : (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-secondary)" }}>Sin datos</div>
        )}
      </div>
      <div style={{ gridColumn: "1 / -1", background: "var(--bg-secondary)", borderRadius: 6, padding: 12 }}>
        <b>Titulares Scalper activos: {String(state.active_titulars ?? 0)}</b>
        {(state.titular_wallets as Array<Record<string, unknown>>)?.length > 0 && (
          <div style={{ marginTop: 4, fontSize: 12 }}>
            {(state.titular_wallets as Array<Record<string, unknown>>).map((t, i) => (
              <div key={i}>
                {String(t.wallet)} — score {t.score != null ? Number(t.score).toFixed(3) : "—"} — tipos: {(t.types as string[])?.join(", ") || "—"}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
