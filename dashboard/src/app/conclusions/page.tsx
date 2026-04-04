"use client";

import { useState, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
  ComposedChart, Area, Line, ReferenceLine,
} from "recharts";
import KpiCard from "@/components/KpiCard";
import { useAutoRefresh, formatPnl, pnlColor } from "@/lib/hooks";

/* ── Design tokens ── */
const C = {
  green: "#00d68f", red: "#ff4d6a", blue: "#4da6ff",
  purple: "#a855f7", yellow: "#ffd93d", orange: "#ff9f43",
  cyan: "#00e5ff", grey: "#6b7280", pink: "#f472b6",
};

const TYPE_COLORS: Record<string, string> = {
  CRYPTO_BTC_DAILY: C.orange, CRYPTO_BTC_WEEKLY: "#cc5500",
  CRYPTO_ETH_DAILY: C.purple, CRYPTO_ETH_WEEKLY: "#7c3aed",
  CRYPTO_OTHER: C.yellow, SOCIAL_COUNT: C.pink,
  POLITICS: C.blue, POLITICS_TRUMP: C.blue,
  MACRO: C.cyan, MACRO_TARIFFS: C.cyan,
  GEOPOLITICS: C.grey, SPORTS: C.green,
  ENTERTAINMENT: C.purple, OTHER_EVENT: C.green,
};

/* ── UI primitives ── */
function Section({ title, id, children }: { title: string; id?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="rounded-xl border p-5" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
      <h2 className="text-base font-bold mb-4" style={{ color: "var(--text-primary)" }}>{title}</h2>
      {children}
    </section>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs font-semibold mr-1 mb-1"
      style={{ background: color + "22", color }}>{label}</span>
  );
}

function Insight({ type, children }: { type: "positive" | "negative" | "neutral" | "education"; children: React.ReactNode }) {
  const colors = { positive: C.green, negative: C.red, neutral: C.blue, education: C.purple };
  const icons = { positive: "+", negative: "!", neutral: "i", education: "?" };
  const bg = colors[type];
  return (
    <div className="flex gap-3 rounded-lg p-3 mb-2 border" style={{ background: bg + "0d", borderColor: bg + "33" }}>
      <span className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
        style={{ background: bg + "22", color: bg }}>{icons[type]}</span>
      <div className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>{children}</div>
    </div>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg p-2 border text-xs" style={{ background: "var(--bg-secondary)", borderColor: "var(--border)" }}>
      <p className="font-semibold mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number"
            ? (p.name.includes("Rate") || p.name.includes("WR") ? `${p.value}%` : `$${p.value.toFixed(2)}`)
            : p.value}
        </p>
      ))}
    </div>
  );
}

function TOCLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="block text-sm py-1 hover:underline" style={{ color: C.blue }}>{children}</a>
  );
}

/* ── Page ── */
export default function ConclusionsPage() {
  const fetcher = useCallback(() => fetch("/api/conclusions").then((r) => r.json()), []);
  const { data, loading } = useAutoRefresh(fetcher, 300000);
  const [showAllTrades, setShowAllTrades] = useState(false);

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="animate-spin w-8 h-8 border-2 rounded-full mx-auto mb-3" style={{ borderColor: C.blue, borderTopColor: "transparent" }} />
          <p style={{ color: "var(--text-secondary)" }}>Cargando analisis...</p>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>Si tarda mucho, la base de datos puede estar bajo carga.</p>
        </div>
      </div>
    );
  }

  if (data.error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center p-6 rounded-xl border" style={{ background: C.red + "0d", borderColor: C.red + "33" }}>
          <p className="font-bold" style={{ color: C.red }}>Base de datos no disponible</p>
          <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>{data.error}</p>
          <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>Reintenta en unos minutos. Si el collector esta corriendo con 2M+ snapshots, puede saturar Supabase temporalmente.</p>
        </div>
      </div>
    );
  }

  const {
    summary, byRun, byScoreBucket, byMomentum, byCloseReason, byDirection,
    byMarketType, byEntryPrice, heatmap, signalStats, tsDetail,
    shadowSummary, tsReversalSummary, tradeList, equityCurve,
  } = data;

  const tsData = byCloseReason?.find((r: any) => r.reason === "TRAILING_STOP");
  const tpData = byCloseReason?.find((r: any) => r.reason === "TAKE_PROFIT");
  const noTsTotal = (summary?.totalPnl ?? 0) - (tsData?.pnl ?? 0);
  const noTsTrades = (summary?.total ?? 0) - (tsData?.n ?? 0);
  const noTsWins = summary?.wins ?? 0;
  const noTsWr = noTsTrades > 0 ? Math.round(noTsWins / noTsTrades * 100) : 0;

  const dirData = [
    { name: "YES", winRate: byDirection?.YES?.winRate ?? 0, pnl: byDirection?.YES?.pnl ?? 0, n: byDirection?.YES?.n ?? 0 },
    { name: "NO", winRate: byDirection?.NO?.winRate ?? 0, pnl: byDirection?.NO?.pnl ?? 0, n: byDirection?.NO?.n ?? 0 },
  ];

  const reasonPie = (byCloseReason ?? []).map((r: any) => ({
    name: r.reason, value: r.n,
    color: r.reason === "TAKE_PROFIT" ? C.green : r.reason === "TRAILING_STOP" ? C.red : r.reason === "RESOLUTION" ? C.blue : C.yellow,
  }));

  return (
    <div className="space-y-6 pb-12">
      {/* ═══ HEADER ═══ */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Informe de Conclusiones
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Analisis retrospectivo completo &mdash; {summary?.total ?? 0} trades, {signalStats?.total ?? 0} senales, {shadowSummary?.total ?? 0} shadow trades
        </p>
      </div>

      {/* ═══ TABLE OF CONTENTS ═══ */}
      <Section title="Indice">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4">
          <div>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>DATOS</p>
            <TOCLink href="#strategy">1. Contexto de la Estrategia</TOCLink>
            <TOCLink href="#kpis">2. KPIs Generales</TOCLink>
            <TOCLink href="#charts">3. Graficos de Rendimiento</TOCLink>
          </div>
          <div>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>ANALISIS</p>
            <TOCLink href="#trailing-stop">4. Deep Dive: Trailing Stop</TOCLink>
            <TOCLink href="#heatmap">5. Heatmap de Edge</TOCLink>
            <TOCLink href="#shadows">6. Shadow Trades</TOCLink>
          </div>
          <div>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>INFORME</p>
            <TOCLink href="#report">7. Informe Completo</TOCLink>
            <TOCLink href="#params">8. Evaluacion de Parametros</TOCLink>
            <TOCLink href="#external">9. Contraste con Informe Externo</TOCLink>
          </div>
        </div>
      </Section>

      {/* ═══ 1. STRATEGY CONTEXT ═══ */}
      <Section title="1. Contexto de la Estrategia: Mean-Reversion via Whale Herding" id="strategy">
        <div className="text-sm space-y-3" style={{ color: "var(--text-secondary)" }}>
          <p><strong style={{ color: "var(--text-primary)" }}>Tesis central:</strong> En mercados de prediccion, cuando las ballenas (wallets grandes) y bots se agrupan masivamente en una direccion, generan un <em>overshoot</em> — el precio se desvia de su valor justo. Nosotros detectamos este herding y apostamos en contra (contrarian), esperando que el precio revierta hacia su fair value.</p>

          <Insight type="education">
            <strong>Por que funciona (en teoria):</strong> Los mercados de prediccion son binarios (SI/NO). Cuando hay herding, el precio refleja el sentimiento de un grupo, no necesariamente la probabilidad real del evento. Esta divergencia crea una oportunidad de mean-reversion. Piensa en ello como: &ldquo;si todos los que van a comprar ya han comprado, no queda quien empuje el precio mas arriba&rdquo;.
          </Insight>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
            <div className="rounded-lg p-3 border" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: C.blue }}>FASE 1: DETECCION</p>
              <p className="text-xs">Tres fuentes de datos para detectar herding: Falcon API (concentracion de wallets top), PolymarketScan (trades grandes reales), y snapshots (velocidad de precio cada 2min). El sistema busca que herding + velocity esten alineados en la misma direccion.</p>
            </div>
            <div className="rounded-lg p-3 border" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: C.purple }}>FASE 2: SCORING (0-100)</p>
              <p className="text-xs">Divergence score (50% peso) + Momentum score (30%) + Smart Wallets (20%) = Total Score. Solo se generan senales si score &ge; 65. Half-Kelly sizing: la apuesta es proporcional a nuestra confianza, con un tope del 5% del capital.</p>
            </div>
            <div className="rounded-lg p-3 border" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: C.orange }}>FASE 3: RISK MANAGEMENT</p>
              <p className="text-xs">Trailing Stop 25% | Take Profit 50% | Timeout 7d | Max 5 posiciones | Cooldown 24h post-stop | Circuit breaker (3 losses = pausa 24h) | Max drawdown 20%.</p>
            </div>
          </div>

          <Insight type="education">
            <strong>Filtro LLM (Claude Haiku):</strong> Antes de ejecutar un trade, un modelo de lenguaje evalua si la apuesta contrarian tiene sentido semantico. Puede rechazar si el mercado es ambiguo, el outcome es casi seguro (&gt;85%), o si es un pure crypto price-target. Opera en modo <em>fail-open</em>: si el LLM falla, el trade pasa igualmente. Actualmente usa <code>claude-haiku-4-5-20251001</code>.
          </Insight>
        </div>
      </Section>

      {/* ═══ 2. KPIs ═══ */}
      <div id="kpis" className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label="Total Trades" value={String(summary?.total ?? 0)} subValue={`${summary?.wins ?? 0}W / ${summary?.losses ?? 0}L`} />
        <KpiCard label="Win Rate" value={`${summary?.winRate ?? 0}%`} color={(summary?.winRate ?? 0) >= 50 ? "green" : "red"} />
        <KpiCard label="P&L Total" value={formatPnl(summary?.totalPnl)} color={(summary?.totalPnl ?? 0) >= 0 ? "green" : "red"} />
        <KpiCard label="Avg Win" value={formatPnl(summary?.avgWin)} color="green" />
        <KpiCard label="Avg Loss" value={formatPnl(summary?.avgLoss)} color="red" />
        <KpiCard label="Win/Loss Ratio" value={`${summary?.winLossRatio ?? 0}x`} color={(summary?.winLossRatio ?? 0) >= 1 ? "green" : "red"} />
      </div>

      {/* Run breakdown */}
      {byRun && byRun.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {byRun.map((r: any) => (
            <div key={r.run} className="rounded-lg p-3 border text-center" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Run {r.run}</p>
              <p className="text-lg font-bold" style={{ color: r.pnl >= 0 ? C.green : C.red }}>{formatPnl(r.pnl)}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{r.n} trades / {r.winRate}% WR</p>
            </div>
          ))}
        </div>
      )}

      {/* ═══ 3. CHARTS ═══ */}
      <div id="charts" className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Equity Curve */}
        <Section title="Curva de Equity">
          <ResponsiveContainer width="100%" height={250}>
            <ComposedChart data={equityCurve ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="trade" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={0} stroke="var(--text-secondary)" strokeDasharray="3 3" />
              <Area type="monotone" dataKey="pnl" fill={C.blue + "33"} stroke={C.blue} name="Cumulative P&L" />
              <Bar dataKey="tradePnl" name="Trade P&L" maxBarSize={8}>
                {(equityCurve ?? []).map((d: any, i: number) => (
                  <Cell key={i} fill={d.tradePnl >= 0 ? C.green : C.red} />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
          <Insight type="education">
            <strong>Como leer este grafico:</strong> La linea azul muestra el P&L acumulado. Las barras verdes/rojas son el resultado de cada trade individual. Fijate en como la curva sube hasta el trade ~14 y luego cae en picado — esa caida corresponde a una racha de trailing stops consecutivos. Es la evidencia visual mas clara de que el TS esta destruyendo valor.
          </Insight>
        </Section>

        {/* Score Bucket */}
        <Section title="Win Rate por Score Bucket">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={byScoreBucket ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="bucket" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} domain={[0, 100]} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="winRate" name="Win Rate %" maxBarSize={40}>
                {(byScoreBucket ?? []).map((d: any, i: number) => (
                  <Cell key={i} fill={d.winRate >= 50 ? C.green : C.red} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap gap-2 mt-2">
            {(byScoreBucket ?? []).map((b: any) => (
              <span key={b.bucket} className="text-xs px-2 py-1 rounded" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                [{b.bucket}] n={b.n} P&L=${b.pnl}
              </span>
            ))}
          </div>
          <Insight type="education">
            <strong>Que nos dice esto:</strong> El edge SOLO existe en score 80+. Los buckets 65-80 pierden dinero consistentemente. Esto sugiere que el threshold de 65 es demasiado bajo — estamos tratando como &ldquo;tradables&rdquo; senales que solo son &ldquo;interesantes de observar&rdquo;. El salto de calidad esta en 80+, no en 75+.
          </Insight>
        </Section>

        {/* Close Reason Distribution */}
        <Section title="Distribucion por Close Reason">
          <div className="flex items-center gap-4">
            <ResponsiveContainer width="50%" height={220}>
              <PieChart>
                <Pie data={reasonPie} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={80}>
                  {reasonPie.map((d: any, i: number) => (<Cell key={i} fill={d.color} />))}
                </Pie>
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="w-1/2 space-y-2">
              {(byCloseReason ?? []).map((r: any) => (
                <div key={r.reason} className="flex justify-between text-xs px-2 py-1.5 rounded" style={{ background: "var(--bg-secondary)" }}>
                  <span style={{ color: "var(--text-primary)" }}>{r.reason}</span>
                  <span>
                    <span style={{ color: r.winRate >= 50 ? C.green : C.red }}>{r.winRate}%</span>
                    <span style={{ color: "var(--text-secondary)" }}> | </span>
                    <span style={{ color: pnlColor(r.pnl) }}>${r.pnl}</span>
                    <span style={{ color: "var(--text-secondary)" }}> | {r.avgHoldHours}h</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Section>

        {/* Direction */}
        <Section title="YES vs NO">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg p-4 border text-center" style={{ borderColor: C.red + "44", background: C.red + "0d" }}>
              <p className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>YES: {byDirection?.YES?.n ?? 0} trades</p>
              <p className="text-2xl font-bold" style={{ color: C.red }}>{byDirection?.YES?.winRate ?? 0}% WR</p>
              <p className="text-sm font-semibold" style={{ color: C.red }}>{formatPnl(byDirection?.YES?.pnl)}</p>
            </div>
            <div className="rounded-lg p-4 border text-center" style={{ borderColor: C.green + "44", background: C.green + "0d" }}>
              <p className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>NO: {byDirection?.NO?.n ?? 0} trades</p>
              <p className="text-2xl font-bold" style={{ color: C.green }}>{byDirection?.NO?.winRate ?? 0}% WR</p>
              <p className="text-sm font-semibold" style={{ color: C.green }}>{formatPnl(byDirection?.NO?.pnl)}</p>
            </div>
          </div>
          <Insight type="education">
            <strong>La asimetria YES/NO es el hallazgo mas importante.</strong> No son la misma estrategia. Los mercados &ldquo;sobrecomprados&rdquo; (precio alto) corrigen con mas violencia que los &ldquo;sobrevendidos&rdquo; (precio bajo). Esto es comun en muchos mercados: la euforia se corrige mas rapido que el pesimismo.
          </Insight>
        </Section>

        {/* Market Type */}
        <Section title="Rendimiento por Tipo de Mercado">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={byMarketType ?? []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis type="number" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis dataKey="type" type="category" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={130} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="pnl" name="P&L $" maxBarSize={20}>
                {(byMarketType ?? []).map((d: any, i: number) => (<Cell key={i} fill={d.pnl >= 0 ? C.green : C.red} />))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap gap-1 mt-2">
            {(byMarketType ?? []).map((m: any) => (
              <span key={m.type} className="text-xs px-2 py-1 rounded"
                style={{ background: (TYPE_COLORS[m.type] || C.grey) + "22", color: TYPE_COLORS[m.type] || C.grey }}>
                {m.type}: {m.n}t / {m.winRate}% / ${m.pnl}
              </span>
            ))}
          </div>
        </Section>

        {/* Entry Price Range */}
        <Section title="Win Rate por Precio de Entrada">
          <ResponsiveContainer width="100%" height={250}>
            <ComposedChart data={byEntryPrice ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="range" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} />
              <YAxis yAxisId="wr" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} domain={[0, 100]} />
              <YAxis yAxisId="pnl" orientation="right" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip />} />
              <Bar yAxisId="wr" dataKey="winRate" name="Win Rate %" maxBarSize={30}>
                {(byEntryPrice ?? []).map((d: any, i: number) => (
                  <Cell key={i} fill={d.winRate >= 50 ? C.green + "aa" : C.red + "aa"} />
                ))}
              </Bar>
              <Line yAxisId="pnl" type="monotone" dataKey="pnl" stroke={C.blue} name="P&L $" strokeWidth={2} dot={{ r: 4 }} />
            </ComposedChart>
          </ResponsiveContainer>
          <Insight type="education">
            <strong>El precio de entrada predice el resultado.</strong> Entradas 0.65-0.80 (= apostar NO en mercados sobrecomprados) tienen WR cercano al 100%. Entradas &lt;0.20 (= apostar YES en longshots) son una trampa. No es que &ldquo;sean baratos y valgan la pena&rdquo; — es que el mercado tiene razon y el evento es improbable.
          </Insight>
        </Section>

        {/* Momentum */}
        <Section title="Impacto del Momentum Score">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byMomentum ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="bucket" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} domain={[0, 100]} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="winRate" name="Win Rate %" maxBarSize={40}>
                {(byMomentum ?? []).map((d: any, i: number) => (
                  <Cell key={i} fill={d.winRate >= 50 ? C.green : C.red} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <Insight type="education">
            <strong>Momentum alto = mejor edge.</strong> Esto parece contraintuitivo para una estrategia contrarian. Pero tiene sentido: las mejores oportunidades no son &ldquo;mercados muertos&rdquo;, sino mercados que se han movido mucho y demasiado rapido. No cualquier divergencia vale — funciona mejor la divergencia con energia.
          </Insight>
        </Section>

        {/* Signal Stats */}
        <Section title="Senales: Generadas vs Ejecutadas">
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div className="rounded-lg p-3 text-center" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{signalStats?.total ?? 0}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Total</p>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: C.green + "0d" }}>
              <p className="text-2xl font-bold" style={{ color: C.green }}>{signalStats?.executed ?? 0}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Ejecutadas ({signalStats?.executionRate ?? 0}%)</p>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: C.yellow + "0d" }}>
              <p className="text-2xl font-bold" style={{ color: C.yellow }}>{signalStats?.expired ?? 0}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Expiradas ({100 - (signalStats?.executionRate ?? 0)}%)</p>
            </div>
          </div>
        </Section>
      </div>

      {/* ═══ 4. TRAILING STOP DEEP DIVE ═══ */}
      <Section title="4. Deep Dive: El Trailing Stop como destructor de valor" id="trailing-stop">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
              {tsData?.n ?? 0} trades cerrados por Trailing Stop con <strong style={{ color: C.red }}>0% win rate</strong> y <strong style={{ color: C.red }}>${tsData?.pnl ?? 0}</strong> de perdida.
            </p>
            <div className="rounded-lg overflow-hidden border" style={{ borderColor: "var(--border)" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: "var(--bg-secondary)" }}>
                    <th className="px-2 py-1.5 text-left">Dir</th>
                    <th className="px-2 py-1.5 text-right">Entry</th>
                    <th className="px-2 py-1.5 text-right">Exit</th>
                    <th className="px-2 py-1.5 text-right">P&L</th>
                    <th className="px-2 py-1.5 text-left">Tipo</th>
                    <th className="px-2 py-1.5 text-left">Mercado</th>
                  </tr>
                </thead>
                <tbody>
                  {(tsDetail ?? []).map((t: any, i: number) => (
                    <tr key={i} className="border-t" style={{ borderColor: "var(--border)" }}>
                      <td className="px-2 py-1" style={{ color: t.direction === "YES" ? C.green : C.red }}>{t.direction}</td>
                      <td className="px-2 py-1 text-right">{t.entry?.toFixed(3)}</td>
                      <td className="px-2 py-1 text-right">{t.exit?.toFixed(3)}</td>
                      <td className="px-2 py-1 text-right" style={{ color: C.red }}>${t.pnl}</td>
                      <td className="px-2 py-1"><Badge label={t.type} color={TYPE_COLORS[t.type] || C.grey} /></td>
                      <td className="px-2 py-1 truncate max-w-[180px]" style={{ color: "var(--text-secondary)" }}>{t.question}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="space-y-3">
            {/* TS Reversal Analysis */}
            {tsReversalSummary && tsReversalSummary.analyzed > 0 && (
              <div className="rounded-lg p-4 border" style={{ borderColor: C.orange + "44", background: C.orange + "0a" }}>
                <p className="text-sm font-semibold mb-2" style={{ color: C.orange }}>Analisis de Reversion Post-Stop</p>
                <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
                  De {tsReversalSummary.analyzed} trades analizados con snapshots posteriores al cierre:
                </p>
                <div className="text-center py-2">
                  <p className="text-3xl font-bold" style={{ color: tsReversalSummary.wouldHaveWonPct > 50 ? C.green : C.yellow }}>
                    {tsReversalSummary.wouldHaveWonPct}%
                  </p>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    habrian ganado si no hubieramos cerrado ({tsReversalSummary.eventuallyWon}/{tsReversalSummary.analyzed})
                  </p>
                </div>
              </div>
            )}

            <div className="rounded-lg p-4 border" style={{ borderColor: C.green + "44", background: C.green + "0a" }}>
              <p className="text-sm font-semibold mb-2" style={{ color: C.green }}>Simulacion sin Trailing Stop</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span style={{ color: "var(--text-secondary)" }}>P&L actual:</span> <span className="font-bold" style={{ color: C.red }}>${summary?.totalPnl}</span></div>
                <div><span style={{ color: "var(--text-secondary)" }}>P&L sin TS:</span> <span className="font-bold" style={{ color: C.green }}>+${Math.round(noTsTotal)}</span></div>
                <div><span style={{ color: "var(--text-secondary)" }}>WR actual:</span> <span className="font-bold">{summary?.winRate}%</span></div>
                <div><span style={{ color: "var(--text-secondary)" }}>WR sin TS:</span> <span className="font-bold" style={{ color: C.green }}>{noTsWr}%</span></div>
              </div>
            </div>

            <Insight type="education">
              <strong>Por que el TS falla en mean-reversion:</strong> Un trailing stop protege contra tendencias adversas prolongadas. Pero en mean-reversion, <em>esperamos</em> que el precio vaya en contra primero (eso es lo que genera la oportunidad). Un TS del 25% en un mercado con 10-20% de volatilidad diaria es como poner una alarma de incendio en una cocina — se va a activar con el uso normal.
            </Insight>
          </div>
        </div>
      </Section>

      {/* ═══ 5. HEATMAP ═══ */}
      {heatmap && heatmap.length > 0 && (
        <Section title="5. Heatmap de Edge: Score + Direccion + Momentum" id="heatmap">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {heatmap.map((h: any) => (
              <div key={h.combo} className="rounded-lg p-3 border" style={{
                borderColor: h.pnl > 0 ? C.green + "44" : h.pnl < -20 ? C.red + "44" : "var(--border)",
                background: h.pnl > 0 ? C.green + "08" : h.pnl < -20 ? C.red + "08" : "var(--bg-secondary)",
              }}>
                <p className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>{h.combo}</p>
                <div className="flex justify-between mt-1">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>n={h.n}</span>
                  <span className="text-xs font-semibold" style={{ color: h.winRate >= 50 ? C.green : C.red }}>{h.winRate}% WR</span>
                  <span className="text-xs font-semibold" style={{ color: pnlColor(h.pnl) }}>${h.pnl}</span>
                </div>
              </div>
            ))}
          </div>
          <Insight type="education">
            <strong>Como leer este heatmap:</strong> Cada celda muestra una combinacion de Score/Direccion/Momentum. Las celdas verdes son combinaciones rentables, las rojas pierden dinero. Busca el patron: las celdas con <strong>80+ / NO / mom60+</strong> deberian ser las mas verdes — ahi vive el edge real. Las celdas con &lt;75 / YES / mom&lt;60 son las mas peligrosas.
          </Insight>
        </Section>
      )}

      {/* ═══ 6. SHADOW TRADES ═══ */}
      {shadowSummary && shadowSummary.total > 0 && (
        <Section title="6. Shadow Trades: Oportunidades Perdidas" id="shadows">
          <div className="grid grid-cols-4 gap-3 mb-3">
            <div className="rounded-lg p-3 text-center" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-xl font-bold">{shadowSummary.total}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Shadow total</p>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-xl font-bold">{shadowSummary.resolved}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Resueltos</p>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: C.green + "0d" }}>
              <p className="text-xl font-bold" style={{ color: C.green }}>{shadowSummary.resolvedWR}%</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>WR estimado</p>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: "var(--bg-secondary)" }}>
              <p className="text-xl font-bold">{shadowSummary.withOutcome}</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Con outcome</p>
            </div>
          </div>
          <Insight type="education">
            <strong>Que son los shadow trades:</strong> Son senales que la estrategia genero pero no pudo ejecutar (por capacidad maxima, drift excesivo, etc). Analizamos su resultado &ldquo;hipotetico&rdquo; para saber si estamos dejando dinero fuera. Si el WR de shadows es mayor que el de trades reales, puede indicar que nuestro filtro de capacidad esta bloqueando trades buenos.
          </Insight>
        </Section>
      )}

      {/* ═══ TRADE TABLE ═══ */}
      <Section title="Todos los Trades">
        <div className="overflow-x-auto rounded-lg border" style={{ borderColor: "var(--border)" }}>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: "var(--bg-secondary)" }}>
                <th className="px-2 py-2 text-left">#</th>
                <th className="px-2 py-2 text-left">Run</th>
                <th className="px-2 py-2 text-left">Dir</th>
                <th className="px-2 py-2 text-right">Score</th>
                <th className="px-2 py-2 text-right">Entry</th>
                <th className="px-2 py-2 text-right">Exit</th>
                <th className="px-2 py-2 text-right">P&L</th>
                <th className="px-2 py-2 text-left">Reason</th>
                <th className="px-2 py-2 text-left">Type</th>
                <th className="px-2 py-2 text-left">Market</th>
              </tr>
            </thead>
            <tbody>
              {(tradeList ?? []).slice(0, showAllTrades ? undefined : 20).map((t: any, i: number) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--border)", background: t.pnl >= 0 ? C.green + "05" : C.red + "05" }}>
                  <td className="px-2 py-1.5" style={{ color: "var(--text-secondary)" }}>{i + 1}</td>
                  <td className="px-2 py-1.5" style={{ color: "var(--text-secondary)" }}>{t.runId ?? "-"}</td>
                  <td className="px-2 py-1.5 font-semibold" style={{ color: t.direction === "YES" ? C.green : C.red }}>{t.direction}</td>
                  <td className="px-2 py-1.5 text-right">{t.score?.toFixed(1)}</td>
                  <td className="px-2 py-1.5 text-right">{t.entry?.toFixed(3)}</td>
                  <td className="px-2 py-1.5 text-right">{t.exit?.toFixed(3)}</td>
                  <td className="px-2 py-1.5 text-right font-semibold" style={{ color: pnlColor(t.pnl) }}>${t.pnl}</td>
                  <td className="px-2 py-1.5"><Badge label={t.closeReason} color={t.closeReason === "TAKE_PROFIT" ? C.green : t.closeReason === "TRAILING_STOP" ? C.red : C.blue} /></td>
                  <td className="px-2 py-1.5"><Badge label={t.type} color={TYPE_COLORS[t.type] || C.grey} /></td>
                  <td className="px-2 py-1.5 truncate max-w-[220px]" style={{ color: "var(--text-secondary)" }}>{t.question}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(tradeList ?? []).length > 20 && (
          <button onClick={() => setShowAllTrades(!showAllTrades)}
            className="text-xs mt-2 px-3 py-1 rounded" style={{ background: C.blue + "22", color: C.blue }}>
            {showAllTrades ? "Mostrar menos" : `Ver todos (${tradeList.length})`}
          </button>
        )}
      </Section>

      {/* ═══════════════════ INFORME ESCRITO ═══════════════════ */}
      <div id="report" className="rounded-xl border p-6" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <h2 className="text-xl font-bold mb-6" style={{ color: "var(--text-primary)" }}>
          7. Informe de Conclusiones
        </h2>

        {/* 7.1 QUE HACE BIEN */}
        <div className="mb-8">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.green, borderColor: "var(--border)" }}>7.1 Que hace bien la estrategia</h3>
          <Insight type="positive">
            <strong>La tesis de mean-reversion via whale herding es correcta.</strong> Los trades que llegan a resolucion natural tienen 67% WR. Esto valida que la idea fundamental funciona: detectar herding y apostar en contra es una estrategia con edge positivo. El problema no esta en la deteccion, sino en la gestion.
          </Insight>
          <Insight type="positive">
            <strong>Take Profit perfectamente calibrado.</strong> 100% WR en trades TP (+$186). El target del 50% captura la reversion completa. Tiempo medio 3.2h = cuando la tesis funciona, funciona rapido. Esto es la firma de un buen setup: resolucion rapida y limpia.
          </Insight>
          <Insight type="positive">
            <strong>La direccion NO es donde vive el edge.</strong> 68% WR en NO vs 22% en YES. Esto tiene logica economica: cuando las ballenas empujan un mercado &ldquo;hacia arriba&rdquo; (sobrecalentandolo), la correccion a la baja es mas rapida y violenta que un rebote al alza en un mercado deprimido.
          </Insight>
          <Insight type="positive">
            <strong>Score 80+ funciona.</strong> 73% WR y +$126 de P&L. Cuando el sistema tiene alta confianza, acierta. La funcion de scoring, aunque mejorable, ya discrimina bien en el extremo superior.
          </Insight>
          <Insight type="positive">
            <strong>Entradas en rango 0.35-0.80 son rentables.</strong> ~67% WR combinado. El bot naturalmente encuentra su edge en mercados con precio intermedio-alto.
          </Insight>
        </div>

        {/* 7.2 QUE HACE MAL */}
        <div className="mb-8">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.red, borderColor: "var(--border)" }}>7.2 Que hace mal la estrategia</h3>
          <Insight type="negative">
            <strong>Error #1: El Trailing Stop contradice la naturaleza del setup.</strong> 16 trades, 0% WR, -$240. El TS se activa con la volatilidad normal del mercado, sacandote de posiciones que habrian ganado si les hubieras dado tiempo. Es como entrar en una posicion contrarian y luego tener miedo de que sea contrarian. El hold medio del TS es 8.6h — ni siquiera llega al dia.
          </Insight>
          <Insight type="negative">
            <strong>Error #2: Umbral de entrada demasiado bajo (65).</strong> Las senales con score 65-79 son &ldquo;interesantes pero no tradables&rdquo;. WR del ~33% en esa zona. Estas senales diluyen el edge real que esta en 80+.
          </Insight>
          <Insight type="negative">
            <strong>Error #3: YES y NO tratados como simetricos.</strong> Son dos estrategias distintas con performance radicalmente diferente. YES necesitaria sus propias reglas de entrada, sizing, y stop — o desactivarse temporalmente.
          </Insight>
          <Insight type="negative">
            <strong>Error #4: Mercados sin mecanismo de reversion.</strong> Tweets de Elon Musk (0/3, -$52), crypto weekly price targets — estos mercados no tienen un &ldquo;fair value&rdquo; hacia el cual revertir. El sistema confunde actividad de ballenas (que es constante en crypto) con herding genuino.
          </Insight>
          <Insight type="negative">
            <strong>Error #5: Re-entry agresivo.</strong> &ldquo;Bitcoin dip $64K&rdquo; tuvo 3 entradas consecutivas, todas TS = -$37. El cooldown de 24h no basta si la misma senal sigue apareciendo.
          </Insight>
        </div>

        {/* 7.3 CONFIANZA */}
        <div className="mb-8">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.blue, borderColor: "var(--border)" }}>7.3 Evaluacion de confianza: Sistema vs Mi analisis</h3>
          <div className="text-sm space-y-3" style={{ color: "var(--text-secondary)" }}>
            <p>He evaluado cada trade comparando la confianza asignada por el sistema con mi propia evaluacion del contexto. Las divergencias principales:</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-lg p-3 border" style={{ borderColor: C.red + "33" }}>
                <p className="text-xs font-semibold mb-1" style={{ color: C.red }}>SOBRECONFIANZA: Crypto Weekly</p>
                <p className="text-xs">Sistema: score 70-87. Mi evaluacion: 40-50. Los mercados tipo &ldquo;BTC reach $70K March 30-April 5&rdquo; no son mean-reversion. Son apuestas direccionales donde la volatilidad semanal de BTC (15-20%) hace impredecible el resultado. El sistema confunde whale activity (constante en crypto) con herding de oportunidad.</p>
              </div>
              <div className="rounded-lg p-3 border" style={{ borderColor: C.red + "33" }}>
                <p className="text-xs font-semibold mb-1" style={{ color: C.red }}>SOBRECONFIANZA: Social Counts</p>
                <p className="text-xs">Sistema: score 74-84 para tweets de Elon. Mi evaluacion: 30-40. No hay fair value ni mecanismo de reversion en conteo de tweets. Es puro ruido. El scoring no puede distinguir si el subyacente tiene dinamica de reversion.</p>
              </div>
              <div className="rounded-lg p-3 border" style={{ borderColor: C.green + "33" }}>
                <p className="text-xs font-semibold mb-1" style={{ color: C.green }}>ALINEAMIENTO: Crypto Daily NO</p>
                <p className="text-xs">Sistema: score 84. Mi evaluacion: 80+. Mercados como &ldquo;BTC above $72K on March 25&rdquo; con direccion NO si tienen mean-reversion intraday. Hay soporte/resistencia clara y la reversion es rapida. Aqui el sistema y yo estamos de acuerdo.</p>
              </div>
              <div className="rounded-lg p-3 border" style={{ borderColor: C.green + "33" }}>
                <p className="text-xs font-semibold mb-1" style={{ color: C.green }}>ALINEAMIENTO: Event Markets</p>
                <p className="text-xs">Politica, entretenimiento, etc. — aqui el herding si indica overshoot genuino. La confianza del sistema coincide con mercados donde la tesis fundamental aplica.</p>
              </div>
            </div>

            <Insight type="education">
              <strong>Conclusion sobre la confianza:</strong> El scoring funciona bien para la deteccion cuantitativa (herding + momentum), pero le falta un filtro cualitativo: &ldquo;tiene este mercado mecanismo de reversion?&rdquo;. La solucion no es ajustar los pesos del score sino filtrar mejor ANTES del scoring. Aqui es donde el LLM filter deberia tener mas peso.
            </Insight>
          </div>
        </div>

        {/* 7.4 TIPOS DE MERCADO */}
        <div className="mb-8">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.purple, borderColor: "var(--border)" }}>7.4 Tipos de mercado: Cuales son validos?</h3>
          <div className="space-y-3">
            <div className="overflow-x-auto rounded-lg border" style={{ borderColor: "var(--border)" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: "var(--bg-secondary)" }}>
                    <th className="px-3 py-2 text-left">Tipo</th>
                    <th className="px-3 py-2 text-center">Veredicto</th>
                    <th className="px-3 py-2 text-left">Razon</th>
                    <th className="px-3 py-2 text-left">Accion</th>
                  </tr>
                </thead>
                <tbody style={{ color: "var(--text-secondary)" }}>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Crypto BTC Daily</td>
                    <td className="px-3 py-2 text-center"><Badge label="VALIDO" color={C.green} /></td>
                    <td className="px-3 py-2">Mean-reversion intraday funciona, especialmente en NO</td>
                    <td className="px-3 py-2">Mantener, preferir NO</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Crypto BTC Weekly</td>
                    <td className="px-3 py-2 text-center"><Badge label="EXCLUIR" color={C.red} /></td>
                    <td className="px-3 py-2">Volatilidad semanal hace impredecible el outcome. Origen de la mayoria de TS losses</td>
                    <td className="px-3 py-2">Filtrar mercados con timeframe &gt;48h y keywords &ldquo;reach/dip&rdquo;</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Crypto ETH</td>
                    <td className="px-3 py-2 text-center"><Badge label="REDUCIR" color={C.yellow} /></td>
                    <td className="px-3 py-2">Peor que BTC por menos liquidez en Polymarket</td>
                    <td className="px-3 py-2">Solo daily, max 1 posicion ETH</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Elon/Social Counts</td>
                    <td className="px-3 py-2 text-center"><Badge label="EXCLUIR" color={C.red} /></td>
                    <td className="px-3 py-2">0% WR. No hay mecanismo de mean-reversion</td>
                    <td className="px-3 py-2">Anadir &ldquo;tweet&rdquo;, &ldquo;post&rdquo; a excluded keywords</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Politica/Geopolitica</td>
                    <td className="px-3 py-2 text-center"><Badge label="VALIDO" color={C.green} /></td>
                    <td className="px-3 py-2">Herding genuino, incertidumbre real, reversion funciona</td>
                    <td className="px-3 py-2">Priorizar</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Entretenimiento</td>
                    <td className="px-3 py-2 text-center"><Badge label="VALIDO" color={C.green} /></td>
                    <td className="px-3 py-2">Buenos resultados, mercados con incertidumbre binaria</td>
                    <td className="px-3 py-2">Mantener</td>
                  </tr>
                  <tr className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">Deportes</td>
                    <td className="px-3 py-2 text-center"><Badge label="EVALUAR" color={C.yellow} /></td>
                    <td className="px-3 py-2">Actualmente excluidos, pero 1 trade (Avalanche) fue ganador</td>
                    <td className="px-3 py-2">Considerar incluir selectivamente</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <Insight type="education">
              <strong>Sobre el LLM Filter:</strong> El filtro actual usa <code>claude-haiku-4-5</code> con un prompt que ya rechaza crypto price-targets. Sin embargo, deja pasar mercados de conteo de tweets y crypto weekly. <strong>Mejora propuesta:</strong> Actualizar el prompt para rechazar: (1) mercados de conteo de actividad social, (2) crypto con timeframe &gt;48h, (3) mercados sin mecanismo claro de mean-reversion. Sobre Haiku vs Sonnet: Haiku 4.5 es suficiente para esta tarea de clasificacion binaria — no necesitas capacidad de razonamiento profundo, sino pattern matching semantico. El coste de Sonnet no se justifica aqui (8x mas caro por call). Lo que si mejoraria es el prompt, no el modelo.
            </Insight>
          </div>
        </div>

        {/* 7.5 APRENDIZAJES */}
        <div className="mb-8">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.yellow, borderColor: "var(--border)" }}>7.5 Aprendizajes y buenas practicas</h3>
          <Insight type="neutral">
            <strong>1. El sistema de salida debe ser coherente con la naturaleza del setup.</strong> Si entras en mean-reversion, tu stop no puede contradecir la tesis. Opciones: (a) eliminar TS y dejar solo timeout + resolution, (b) trailing solo despues de +25% de beneficio, (c) time-based exit (si tras 24-48h no hay progreso, cerrar), (d) TS mucho mas ancho (45-50%).
          </Insight>
          <Insight type="neutral">
            <strong>2. Separar YES y NO como subestrategias.</strong> Cada una necesita sus propias reglas de score minimo, filtros, sizing, y stops. Mezclarlas bajo un mismo framework oculta donde esta el edge.
          </Insight>
          <Insight type="neutral">
            <strong>3. Medir calidad del trade, no solo resultado.</strong> Empezar a guardar MAE (maximum adverse excursion) y MFE (maximum favorable excursion) por trade. Esto permite optimizar stops y TPs con datos reales en vez de porcentajes arbitrarios.
          </Insight>
          <Insight type="neutral">
            <strong>4. Filtro semantico ANTES del scoring.</strong> Los mercados sin mecanismo de reversion no deberian llegar al scoring. El LLM filter es el lugar correcto para esto — mejorar el prompt, no cambiar de modelo.
          </Insight>
          <Insight type="neutral">
            <strong>5. Scoring multiplicativo, no solo aditivo.</strong> El score actual suma factores. Considerar: ciertos factores deben ser obligatorios (momentum &ge; 60) no solo sumar puntos. Un score de 75 con momentum 80 es muy diferente de un score de 75 con momentum 30.
          </Insight>
          <Insight type="neutral">
            <strong>6. Cautela con la muestra.</strong> 37 trades no son estadisticamente significativos. Todas estas conclusiones son indicativas, no definitivas. No hacer cambios drasticos — ajustes incrementales y reversibles. Acumular 100+ trades antes de tomar decisiones definitivas.
          </Insight>
        </div>

        {/* 7.6 PARAMETROS */}
        <div className="mb-8" id="params">
          <h3 className="text-base font-bold mb-3 pb-2 border-b" style={{ color: C.cyan, borderColor: "var(--border)" }}>7.6 Evaluacion de parametros</h3>
          <div className="overflow-x-auto rounded-lg border" style={{ borderColor: "var(--border)" }}>
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: "var(--bg-secondary)" }}>
                  <th className="px-3 py-2 text-left">Parametro</th>
                  <th className="px-3 py-2 text-center">Actual</th>
                  <th className="px-3 py-2 text-center">Propuesta</th>
                  <th className="px-3 py-2 text-left">Razon basada en datos</th>
                  <th className="px-3 py-2 text-center">Prioridad</th>
                </tr>
              </thead>
              <tbody style={{ color: "var(--text-secondary)" }}>
                {[
                  { param: "TRAILING_STOP_PCT", actual: "25%", proposal: "Eliminar o 45%", reason: "0% WR en 16 trades. -$240 destruidos. Incompatible con mean-reversion.", priority: "CRITICA", color: C.red },
                  { param: "SIGNAL_THRESHOLD", actual: "65", proposal: "78", reason: "Solo 80+ es rentable. 65-79 pierde dinero. Subir a 78 como compromiso.", priority: "ALTA", color: C.orange },
                  { param: "MIN_CONTRARIAN_PRICE", actual: "0.20", proposal: "0.30", reason: "Entradas <0.20 tienen ~0% WR. Son longshots disfrazados.", priority: "ALTA", color: C.orange },
                  { param: "TAKE_PROFIT_PCT", actual: "50%", proposal: "50% (mantener)", reason: "100% WR en 7 trades. Bien calibrado.", priority: "OK", color: C.green },
                  { param: "Momentum filter", actual: "No hard filter", proposal: "Exigir mom >= 60", reason: "WR 54% con mom 60+ vs 27% con mom 30-60.", priority: "MEDIA", color: C.yellow },
                  { param: "Cooldown re-entry", actual: "24h", proposal: "48h + max 1/market", reason: "Re-entries al mismo market amplificaron perdidas 3x.", priority: "MEDIA", color: C.yellow },
                  { param: "LLM prompt", actual: "Basico", proposal: "Anadir filtro social + weekly crypto", reason: "Elon tweets y crypto weekly pasaron el filtro LLM.", priority: "MEDIA", color: C.yellow },
                  { param: "MAX_OPEN_POSITIONS", actual: "5", proposal: "5 (mantener)", reason: "59% expiran. Se podria subir a 7, pero primero mejorar calidad.", priority: "BAJA", color: C.grey },
                ].map((row, i) => (
                  <tr key={i} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-semibold">{row.param}</td>
                    <td className="px-3 py-2 text-center">{row.actual}</td>
                    <td className="px-3 py-2 text-center" style={{ color: C.green }}>{row.proposal}</td>
                    <td className="px-3 py-2">{row.reason}</td>
                    <td className="px-3 py-2 text-center"><Badge label={row.priority} color={row.color} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 7.7 RESUMEN EJECUTIVO */}
        <div className="rounded-xl p-5 border-2 mb-8" style={{ borderColor: C.blue + "66", background: C.blue + "08" }}>
          <h3 className="text-base font-bold mb-3" style={{ color: C.blue }}>Resumen Ejecutivo</h3>
          <div className="text-sm space-y-2" style={{ color: "var(--text-secondary)" }}>
            <p><strong style={{ color: "var(--text-primary)" }}>La tesis es correcta. La implementacion la esta saboteando.</strong></p>
            <p>El sistema ha encontrado una ventaja parcial real en un nicho concreto: <strong>mercados de eventos, score 80+, direccion NO, con momentum fuerte</strong>. Pero esta diluyendo ese edge con:</p>
            <ol className="list-decimal ml-5 space-y-1">
              <li>Un trailing stop que destruye -$240 en trades que habrian revertido</li>
              <li>Senales mediocres (65-79) que pierden dinero consistentemente</li>
              <li>Mercados sin mecanismo de reversion (tweets, crypto weekly)</li>
              <li>Direccion YES tratada igual que NO cuando su performance es opuesta</li>
            </ol>
            <p className="mt-3"><strong style={{ color: "var(--text-primary)" }}>Regla provisional recomendada para validar el edge real:</strong></p>
            <div className="rounded-lg p-3 mt-2 border" style={{ borderColor: C.green + "44", background: C.green + "0a" }}>
              <p className="font-mono text-xs" style={{ color: C.green }}>
                Solo NO + Score &ge; 80 + Momentum &ge; 60 + Sin trailing stop temprano
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                Esto no es la version final, pero es la forma mas limpia de aislar si el edge base es realmente rentable cuando dejas de sabotearlo.
              </p>
            </div>
            <p className="mt-3 text-xs italic">Nota: 37 trades no son estadisticamente significativos. Estas conclusiones son indicativas. Acumular 100+ trades antes de cambios agresivos.</p>
          </div>
        </div>
      </div>

      {/* ═══ 9. EXTERNAL REPORT COMPARISON ═══ */}
      <div id="external" className="rounded-xl border p-6" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <h2 className="text-lg font-bold mb-4" style={{ color: "var(--text-primary)" }}>
          9. Contraste con Informe Externo
        </h2>
        <div className="text-sm space-y-4" style={{ color: "var(--text-secondary)" }}>
          <p>Un analisis externo independiente evaluo la misma data. Aqui comparo sus conclusiones con las mias para identificar puntos de vista adicionales:</p>

          <div className="rounded-lg p-4 border" style={{ borderColor: C.green + "33" }}>
            <p className="font-semibold mb-2" style={{ color: C.green }}>Coincidencias (valida nuestro analisis)</p>
            <ul className="text-xs space-y-1.5 list-disc ml-4">
              <li><strong>El edge esta en score 80+, direccion NO, momentum 60+</strong> — ambos analisis llegan a la misma conclusion central.</li>
              <li><strong>El trailing stop es el destructor #1</strong> — coincidencia total: incompatible con mean-reversion.</li>
              <li><strong>YES y NO son dos estrategias distintas</strong> — ambos recomiendan separar o pausar YES.</li>
              <li><strong>El TP del 50% esta bien calibrado</strong> — no tocar lo que funciona.</li>
              <li><strong>El threshold de 65 es demasiado bajo</strong> — coincidencia en subir a 78-80.</li>
            </ul>
          </div>

          <div className="rounded-lg p-4 border" style={{ borderColor: C.orange + "33" }}>
            <p className="font-semibold mb-2" style={{ color: C.orange }}>Perspectivas adicionales del informe externo</p>
            <ul className="text-xs space-y-1.5 list-disc ml-4">
              <li><strong>RESOLUTION con WR 67% pero P&L negativo</strong> — El externo senala que ganar 67% de las veces y perder dinero indica que los ganadores por resolution son pequenos y los perdedores grandes. Esto sugiere que el entry price importa tanto como la direccion. <em>Mi evaluacion: de acuerdo, esto refuerza la necesidad de subir MIN_CONTRARIAN_PRICE.</em></li>
              <li><strong>Scoring aditivo vs multiplicativo</strong> — El externo sugiere que el scoring deberia pasar de &ldquo;suma de senales&rdquo; a &ldquo;selector de edge&rdquo; con factores obligatorios. <em>Mi evaluacion: valioso. Un momentum de 30 no deberia compensarse con divergence alta — deberia ser un filtro duro.</em></li>
              <li><strong>MAE/MFE como metricas nuevas</strong> — Recomienda medir Maximum Adverse Excursion y Maximum Favorable Excursion por trade. <em>Mi evaluacion: excelente sugerencia para calibrar stops con datos reales.</em></li>
              <li><strong>Trailing solo despues de +25-30% beneficio</strong> — Variante interesante: no activar trailing hasta que el trade vaya positivo, evitando que te saque en la fase inicial de ruido. <em>Mi evaluacion: esta podria ser la mejor solucion intermedia entre eliminar TS y mantenerlo.</em></li>
              <li><strong>Fases de implementacion</strong> — Sugiere un orden: primero aislar edge (solo NO+80+), luego separar estrategias, luego rehacer exits, luego scoring. <em>Mi evaluacion: de acuerdo con la secuencia, es la forma mas conservadora de validar cada mejora.</em></li>
            </ul>
          </div>

          <div className="rounded-lg p-4 border" style={{ borderColor: C.blue + "33" }}>
            <p className="font-semibold mb-2" style={{ color: C.blue }}>Puntos donde discrepo o matizo</p>
            <ul className="text-xs space-y-1.5 list-disc ml-4">
              <li><strong>Sobre las senales expiradas</strong> — El externo dice &ldquo;no es prioridad&rdquo;. Yo matizo: si los shadow trades muestran WR significativamente mayor que los ejecutados, podria indicar que el filtro de capacidad esta bloqueando trades buenos. Merece al menos un analisis rapido.</li>
              <li><strong>Sobre cortar YES completamente</strong> — El externo lo recomienda. Yo prefiero primero entender POR QUE YES falla: si es por entry price bajo (longshots), se resuelve subiendo MIN_CONTRARIAN_PRICE. Si es estructural, entonces si cortarlo.</li>
            </ul>
          </div>

          <Insight type="education">
            <strong>Metodologia de contraste:</strong> Cuando tienes dos analisis independientes sobre los mismos datos, el valor esta en: (1) las coincidencias validan las conclusiones, (2) las divergencias senalan areas donde la evidencia es ambigua y requiere mas datos, (3) las perspectivas nuevas amplian el marco de analisis. En este caso, la coincidencia del 90% entre ambos informes da bastante confianza en las conclusiones principales.
          </Insight>
        </div>
      </div>
    </div>
  );
}
