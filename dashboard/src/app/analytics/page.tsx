"use client";

import { useState, useCallback, useEffect } from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts";
import KpiCard from "@/components/KpiCard";
import { useAutoRefresh, formatPnl, formatPct, pnlColor } from "@/lib/hooks";

const COLORS = { green: "#00d68f", red: "#ff4d6a", blue: "#4da6ff", purple: "#a855f7", yellow: "#ffd93d" };

function tsAgo(iso: string | null): string {
  if (!iso) return "?";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h ago`;
  return h > 0 ? `${h}h ${m}m ago` : `${m}m ago`;
}

// ── Health Check Modal ──────────────────────────────────────────────────────
function HealthModal({ data, onClose }: { data: any; onClose: () => void }) {
  const ok = (v: boolean) => v
    ? <span style={{ color: COLORS.green }}>OK</span>
    : <span style={{ color: COLORS.red }}>WARN</span>;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onClose}>
      <div className="rounded-xl border w-full max-w-lg max-h-[90vh] overflow-y-auto"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
        onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div>
            <h3 className="font-bold text-base">Bot Health Check</h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {new Date(data.timestamp).toLocaleString()}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="px-2 py-0.5 rounded text-xs font-bold"
              style={{
                background: data.status === "OK" ? "var(--green-dim)" : "var(--red-dim)",
                color: data.status === "OK" ? COLORS.green : COLORS.red,
              }}>
              {data.status}
            </span>
            <button onClick={onClose} className="text-xl leading-none opacity-50 hover:opacity-100">×</button>
          </div>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm">
          {/* Issues */}
          {data.issues.length > 0 && (
            <div className="rounded-lg p-3 border" style={{ background: "var(--red-dim)", borderColor: COLORS.red }}>
              {data.issues.map((i: string) => (
                <p key={i} style={{ color: COLORS.red }}>⚠ {i}</p>
              ))}
            </div>
          )}

          {/* Portfolio */}
          {data.portfolio && (
            <div>
              <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>PORTFOLIO</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Capital</span><span className="font-medium">${data.portfolio.capital?.toFixed(2)}</span></div>
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>P&L</span><span className="font-medium" style={{ color: pnlColor(data.portfolio.pnl) }}>${data.portfolio.pnl?.toFixed(2)} ({(data.portfolio.pnlPct * 100)?.toFixed(1)}%)</span></div>
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Win Rate</span><span className="font-medium">{(data.portfolio.winRate * 100)?.toFixed(0)}% ({data.portfolio.wins}W/{data.portfolio.losses}L)</span></div>
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Max Drawdown</span><span className="font-medium">{(data.portfolio.maxDrawdown * 100)?.toFixed(1)}%</span></div>
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Positions</span><span className="font-medium">{data.portfolio.openPositions}/{data.portfolio.maxOpenPositions} open</span></div>
                <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Circuit</span><span className="font-medium">{data.portfolio.circuitBroken ? <span style={{ color: COLORS.red }}>BROKEN</span> : <span style={{ color: COLORS.green }}>OK</span>}</span></div>
              </div>
            </div>
          )}

          {/* Open positions */}
          <div>
            <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>POSICIONES ABIERTAS ({data.openTrades.length})</p>
            {data.openTrades.length === 0
              ? <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Ninguna</p>
              : data.openTrades.map((t: any) => (
                <div key={t.id} className="flex justify-between text-xs py-1 border-b" style={{ borderColor: "var(--border)" }}>
                  <span className="font-mono opacity-60">{t.id.slice(0, 8)}</span>
                  <span className="px-1.5 rounded text-xs font-bold"
                    style={{ background: t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)", color: t.direction === "YES" ? COLORS.green : COLORS.red }}>
                    {t.direction}
                  </span>
                  <span>@ {t.entry_price}</span>
                  <span style={{ color: "var(--text-secondary)" }}>{tsAgo(t.opened_at)}</span>
                </div>
              ))}
          </div>

          {/* Activity 24h */}
          <div>
            <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>ACTIVIDAD ÚLTIMAS 24H</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Señales</span><span className="font-medium">{data.activity24h.signalsGenerated}</span></div>
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Trades abiertos</span><span className="font-medium">{data.activity24h.tradesOpened}</span></div>
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Trades cerrados</span><span className="font-medium">{data.activity24h.tradesClosed}</span></div>
            </div>
            {data.activity24h.closedTrades.map((t: any, i: number) => (
              <div key={i} className="flex gap-3 text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                <span>{t.direction}</span>
                <span>{t.close_reason}</span>
                <span style={{ color: pnlColor(t.pnl_usd) }}>{formatPnl(t.pnl_usd)}</span>
              </div>
            ))}
          </div>

          {/* Collector */}
          <div>
            <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>COLLECTOR</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Estado</span><span>{ok(data.collector.ok)}</span></div>
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Último snapshot</span><span className="font-medium">{tsAgo(data.collector.lastSnapAt)}</span></div>
              <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Snapshots/hora</span><span className="font-medium">{data.collector.snapshotsLastHour}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────
export default function AnalyticsPage() {
  const [runId, setRunId] = useState<string>("");
  const [didAutoSelect, setDidAutoSelect] = useState(false);
  const [healthData, setHealthData] = useState<any>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  const statsFetcher = useCallback(() => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    return fetch(`/api/stats?${params}`).then((r) => r.json());
  }, [runId]);
  const { data: stats } = useAutoRefresh<any>(statsFetcher, 60000);

  useEffect(() => {
    if (!didAutoSelect && stats?.runs?.length > 0) {
      setRunId(String(stats.runs[0].id));
      setDidAutoSelect(true);
    }
  }, [stats, didAutoSelect]);

  const tradesFetcher = useCallback(() => {
    const params = new URLSearchParams({ status: "CLOSED", limit: "500" });
    if (runId) params.set("run_id", runId);
    return fetch(`/api/trades?${params}`).then((r) => r.json());
  }, [runId]);
  const { data: allTrades } = useAutoRefresh<any[]>(tradesFetcher, 60000);

  // Shadow trades
  const [historyTab, setHistoryTab] = useState<"real" | "shadow">("real");

  const shadowFetcher = useCallback(() => fetch("/api/health").then((r) => r.json()), []);
  const { data: healthLive } = useAutoRefresh<any>(shadowFetcher, 60000);

  const shadowTradesFetcher = useCallback(() => fetch("/api/shadow-trades?limit=500").then((r) => r.json()), []);
  const { data: shadowTrades } = useAutoRefresh<any[]>(shadowTradesFetcher, 60000);

  const handleHealthCheck = async () => {
    setHealthLoading(true);
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      setHealthData(data);
    } finally {
      setHealthLoading(false);
    }
  };

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 rounded-full"
          style={{ borderColor: "var(--border)", borderTopColor: "var(--blue)" }} />
      </div>
    );
  }

  const shadow = healthLive?.shadow;
  const shadowWinRate = shadow?.winRate != null ? Math.round(shadow.winRate * 100) : null;
  const actualWinRate = stats.wins + stats.losses > 0
    ? Math.round((stats.wins / (stats.wins + stats.losses)) * 100)
    : 0;
  const wrDelta = shadowWinRate != null ? shadowWinRate - actualWinRate : null;

  const winLossData = [
    { name: "Wins", value: stats.wins },
    { name: "Losses", value: stats.losses },
  ];

  const closeReasonData = Object.entries(stats.byCloseReason as Record<string, { count: number; pnl: number }>)
    .map(([reason, { count, pnl }]) => ({ reason, count, pnl: Math.round(pnl * 100) / 100 }))
    .sort((a, b) => b.count - a.count);

  const calendarData = Object.entries(stats.dailyPnl as Record<string, number>)
    .map(([date, pnl]) => ({ date, pnl: Math.round(pnl * 100) / 100 }))
    .sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Health check modal */}
      {healthData && <HealthModal data={healthData} onClose={() => setHealthData(null)} />}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Analytics</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Strategy performance & deep analysis
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleHealthCheck}
            disabled={healthLoading}
            className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-opacity hover:opacity-80 disabled:opacity-50 flex items-center gap-1.5"
            style={{ background: "var(--bg-secondary)", borderColor: "var(--border)", color: "var(--text-primary)" }}>
            {healthLoading
              ? <><span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> Checking...</>
              : <>⚡ Health Check</>}
          </button>
          {stats.runs?.length > 0 && (
            <select
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              className="px-3 py-1.5 rounded-lg text-sm border"
              style={{ background: "var(--bg-secondary)", borderColor: "var(--border)", color: "var(--text-primary)" }}>
              <option value="">All Runs</option>
              {stats.runs.map((r: any) => (
                <option key={r.id} value={r.id}>
                  Run {r.id} {r.note ? `— ${r.note}` : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Closed Trades" value={stats.totalTrades.toString()} />
        <KpiCard label="Win Rate" value={`${actualWinRate}%`}
          subValue={`${stats.wins}W / ${stats.losses}L`}
          color={stats.wins > stats.losses ? "green" : "red"} />
        <KpiCard label="Avg Win" value={formatPnl(stats.avgWin)} color="green" />
        <KpiCard label="Avg Loss" value={formatPnl(stats.avgLoss)} color="red" />
        <KpiCard label="Avg Hold" value={`${stats.avgHoldTimeHours}h`} />
        <KpiCard label="Profit Factor"
          value={stats.avgLoss !== 0 ? Math.abs(stats.avgWin / stats.avgLoss).toFixed(2) : "—"}
          color={Math.abs(stats.avgWin) > Math.abs(stats.avgLoss) ? "green" : "red"} />
      </div>

      {/* Shadow Trades — Signal Quality */}
      {shadow && (
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold">Signal Quality — Shadow Portfolio</h3>
            <div className="group relative">
              <div className="w-5 h-5 rounded-full border flex items-center justify-center text-xs cursor-default select-none"
                style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>i</div>
              <div className="absolute right-0 top-7 w-72 rounded-lg p-3 text-xs leading-relaxed z-20 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
                Cuando el bot no puede abrir un trade real (máximo de posiciones o circuit breaker), registra un <strong style={{ color: "var(--text-primary)" }}>shadow trade</strong> con la misma señal. Esto permite medir la calidad de la estrategia de detección de oportunidades de forma independiente al capital disponible.
                <br /><br />
                <strong style={{ color: "var(--text-primary)" }}>WR Delta</strong> compara el win rate de las señales no ejecutadas vs las reales. Si shadow WR &gt; actual WR, la estrategia genera más oportunidades buenas de las que se están aprovechando.
              </div>
            </div>
          </div>

          {!shadow.tableExists ? (
            <p className="text-xs" style={{ color: COLORS.red }}>
              Tabla shadow_trades no encontrada — ejecutar setup_shadow_trades.sql en Supabase
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <KpiCard label="Shadow Closed" value={shadow.closed.toString()} />
                <KpiCard label="Shadow Open" value={shadow.open.toString()} />
                <KpiCard
                  label="Shadow WR"
                  value={shadow.closed > 0 && shadowWinRate != null ? `${shadowWinRate}%` : "—"}
                  subValue={shadow.closed > 0 ? `${shadow.wins}W / ${shadow.closed - shadow.wins}L` : undefined}
                  color={shadow.closed > 0 && shadowWinRate != null ? (shadowWinRate >= 50 ? "green" : "red") : undefined}
                />
                <KpiCard
                  label="Actual WR"
                  value={`${actualWinRate}%`}
                  subValue={`${stats.wins}W / ${stats.losses}L`}
                  color={actualWinRate >= 50 ? "green" : "red"}
                />
                <KpiCard
                  label="WR Delta"
                  value={shadow.closed > 0 && wrDelta != null ? `${wrDelta >= 0 ? "+" : ""}${wrDelta}pp` : "—"}
                  subValue={shadow.closed > 0 && wrDelta != null
                    ? (wrDelta > 5 ? "Raise positions" : wrDelta < -5 ? "Filter works" : "Consistent")
                    : undefined}
                  color={shadow.closed > 0 && wrDelta != null
                    ? (wrDelta > 5 ? "green" : wrDelta < -5 ? "red" : "blue") as any
                    : undefined}
                />
                <KpiCard
                  label="Shadow P&L"
                  value={shadow.closed > 0 ? formatPnl(shadow.totalPnl) : "—"}
                  color={shadow.closed > 0 ? (shadow.totalPnl >= 0 ? "green" : "red") : undefined}
                />
              </div>

              {shadow.closed > 0 && Object.keys(shadow.byCloseReason).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.entries(shadow.byCloseReason as Record<string, number>).map(([reason, count]) => (
                    <span key={reason} className="px-2 py-0.5 rounded text-xs border"
                      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
                      {reason}: {count}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Equity Curve */}
      {stats.equityCurve.length > 0 && (
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
            Equity Curve (all closed trades)
          </h3>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={stats.equityCurve}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.blue} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={COLORS.blue} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                formatter={(value: any, name: any) => [
                  `$${Number(value).toFixed(2)}`,
                  name === "pnl" ? "Cumulative P&L" : "Trade P&L",
                ]} />
              <Area type="monotone" dataKey="pnl" stroke={COLORS.blue} fill="url(#eqGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Win/Loss Donut */}
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>Win/Loss Ratio</h3>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={winLossData} cx="50%" cy="50%" innerRadius={50} outerRadius={75}
                dataKey="value" strokeWidth={0}>
                <Cell fill={COLORS.green} />
                <Cell fill={COLORS.red} />
              </Pie>
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Direction P&L */}
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>P&L by Direction</h3>
          <div className="space-y-4 mt-4">
            {([
              { label: "YES", data: stats.byDirection.YES, color: COLORS.green },
              { label: "NO", data: stats.byDirection.NO, color: COLORS.blue },
            ]).map(({ label, data, color }) => (
              <div key={label}>
                <div className="flex justify-between text-sm mb-1">
                  <span style={{ color }}>{label}</span>
                  <span style={{ color: pnlColor(data.pnl) }}>{formatPnl(data.pnl)}</span>
                </div>
                <div className="flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
                  <span>{data.count} trades</span>
                  <span>WR: {data.winRate}%</span>
                </div>
                <div className="w-full h-1.5 rounded-full mt-1" style={{ background: "var(--bg-primary)" }}>
                  <div className="h-full rounded-full" style={{ width: `${data.winRate}%`, background: color }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Close Reason */}
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>By Close Reason</h3>
          {closeReasonData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={closeReasonData} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="reason" tick={{ fontSize: 10 }} width={100} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                  formatter={(value: any, name: any) => [name === "count" ? value : `$${value}`, name === "count" ? "Trades" : "P&L"]} />
                <Bar dataKey="count" fill={COLORS.blue} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm mt-4" style={{ color: "var(--text-secondary)" }}>No data yet</p>
          )}
        </div>
      </div>

      {/* Calendar Heatmap */}
      {calendarData.length > 0 && (
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>Daily P&L Calendar</h3>
          <div className="flex flex-wrap gap-1.5">
            {calendarData.map(({ date, pnl }) => (
              <div key={date} className="group relative">
                <div className="w-10 h-10 rounded-md flex flex-col items-center justify-center text-xs cursor-default border"
                  style={{
                    background: pnl > 0 ? "var(--green-dim)" : pnl < 0 ? "var(--red-dim)" : "var(--bg-secondary)",
                    borderColor: pnl > 0 ? "var(--green)" : pnl < 0 ? "var(--red)" : "var(--border)",
                    color: pnl > 0 ? "var(--green)" : pnl < 0 ? "var(--red)" : "var(--text-secondary)",
                  }}>
                  <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>{date.slice(8)}</span>
                  <span className="font-bold">{pnl > 0 ? "+" : ""}{pnl.toFixed(0)}</span>
                </div>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 rounded text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10"
                  style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
                  {date}: {formatPnl(pnl)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Best & Worst Trades */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {stats.bestTrade && (
          <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
            <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Best Trade</h3>
            <p className="text-lg font-bold" style={{ color: COLORS.green }}>{formatPnl(stats.bestTrade.pnl_usd)}</p>
            <p className="text-sm mt-1 truncate">{stats.bestTrade.market_question}</p>
            <div className="flex gap-4 mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
              <span>{stats.bestTrade.direction}</span>
              <span>Entry: ${stats.bestTrade.entry_price?.toFixed(3)}</span>
              <span>Exit: ${stats.bestTrade.exit_price?.toFixed(3)}</span>
              <span>{formatPct((stats.bestTrade.pnl_pct ?? 0) * 100)}</span>
            </div>
          </div>
        )}
        {stats.worstTrade && (
          <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
            <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Worst Trade</h3>
            <p className="text-lg font-bold" style={{ color: COLORS.red }}>{formatPnl(stats.worstTrade.pnl_usd)}</p>
            <p className="text-sm mt-1 truncate">{stats.worstTrade.market_question}</p>
            <div className="flex gap-4 mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
              <span>{stats.worstTrade.direction}</span>
              <span>Entry: ${stats.worstTrade.entry_price?.toFixed(3)}</span>
              <span>Exit: ${stats.worstTrade.exit_price?.toFixed(3)}</span>
              <span>{formatPct((stats.worstTrade.pnl_pct ?? 0) * 100)}</span>
            </div>
          </div>
        )}
      </div>

      {/* Trade History — tabbed */}
      <div className="rounded-xl border overflow-hidden" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <div className="px-5 py-3 border-b flex items-center justify-between" style={{ borderColor: "var(--border)" }}>
          {/* Tabs */}
          <div className="flex gap-1 p-1 rounded-lg" style={{ background: "var(--bg-primary)" }}>
            {(["real", "shadow"] as const).map((tab) => (
              <button key={tab} onClick={() => setHistoryTab(tab)}
                className="px-3 py-1 rounded-md text-xs font-medium transition-colors"
                style={{
                  background: historyTab === tab ? "var(--bg-card)" : "transparent",
                  color: historyTab === tab ? "var(--text-primary)" : "var(--text-secondary)",
                }}>
                {tab === "real" ? `Trades reales (${(allTrades ?? []).length})` : `Shadow trades (${(shadowTrades ?? []).length})`}
              </button>
            ))}
          </div>
          {historyTab === "real" && <ExportButton trades={allTrades ?? []} />}
        </div>

        <div className="overflow-x-auto max-h-96">
          {historyTab === "real" ? (
            <table className="w-full text-sm">
              <thead className="sticky top-0" style={{ background: "var(--bg-card)" }}>
                <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left px-5 py-2 font-medium">Date</th>
                  <th className="text-left px-3 py-2 font-medium">Market</th>
                  <th className="text-center px-3 py-2 font-medium">Side</th>
                  <th className="text-right px-3 py-2 font-medium">Entry</th>
                  <th className="text-right px-3 py-2 font-medium">Exit</th>
                  <th className="text-right px-3 py-2 font-medium">Size</th>
                  <th className="text-right px-3 py-2 font-medium">P&L</th>
                  <th className="text-right px-3 py-2 font-medium">Return</th>
                  <th className="text-right px-3 py-2 font-medium">Hold</th>
                  <th className="text-right px-5 py-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {(allTrades ?? []).map((t: any) => {
                  const holdHours = t.opened_at && t.closed_at
                    ? ((new Date(t.closed_at).getTime() - new Date(t.opened_at).getTime()) / (1000 * 60 * 60)).toFixed(1)
                    : "—";
                  return (
                    <tr key={t.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                      <td className="px-5 py-2 whitespace-nowrap" style={{ color: "var(--text-secondary)" }}>
                        {(t.closed_at ?? t.opened_at)?.slice(0, 10)}
                      </td>
                      <td className="px-3 py-2 max-w-48 truncate">{t.market_question}</td>
                      <td className="text-center px-3 py-2">
                        <span className="px-2 py-0.5 rounded text-xs font-bold"
                          style={{
                            background: t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                            color: t.direction === "YES" ? "var(--green)" : "var(--red)",
                          }}>
                          {t.direction}
                        </span>
                      </td>
                      <td className="text-right px-3 py-2">${t.entry_price?.toFixed(3)}</td>
                      <td className="text-right px-3 py-2">{t.exit_price ? `$${t.exit_price.toFixed(3)}` : "—"}</td>
                      <td className="text-right px-3 py-2">${t.position_usd?.toFixed(2)}</td>
                      <td className="text-right px-3 py-2 font-medium" style={{ color: pnlColor(t.pnl_usd) }}>
                        {formatPnl(t.pnl_usd)}
                      </td>
                      <td className="text-right px-3 py-2" style={{ color: pnlColor(t.pnl_pct) }}>
                        {formatPct((t.pnl_pct ?? 0) * 100)}
                      </td>
                      <td className="text-right px-3 py-2" style={{ color: "var(--text-secondary)" }}>{holdHours}h</td>
                      <td className="text-right px-5 py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                        {t.close_reason ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0" style={{ background: "var(--bg-card)" }}>
                <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left px-5 py-2 font-medium">Date</th>
                  <th className="text-left px-3 py-2 font-medium">Market</th>
                  <th className="text-center px-3 py-2 font-medium">Side</th>
                  <th className="text-right px-3 py-2 font-medium">Entry</th>
                  <th className="text-right px-3 py-2 font-medium">Exit</th>
                  <th className="text-right px-3 py-2 font-medium">Size</th>
                  <th className="text-right px-3 py-2 font-medium">P&L</th>
                  <th className="text-right px-3 py-2 font-medium">Return</th>
                  <th className="text-right px-3 py-2 font-medium">Reason</th>
                  <th className="text-right px-5 py-2 font-medium">Bloqueado</th>
                </tr>
              </thead>
              <tbody>
                {(shadowTrades ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={10} className="px-5 py-8 text-center text-xs" style={{ color: "var(--text-secondary)" }}>
                      Sin shadow trades aún
                    </td>
                  </tr>
                ) : (shadowTrades ?? []).map((t: any) => (
                  <tr key={t.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-5 py-2 whitespace-nowrap" style={{ color: "var(--text-secondary)" }}>
                      {(t.exit_at ?? t.entry_at)?.slice(0, 10)}
                    </td>
                    <td className="px-3 py-2 max-w-48 truncate">{t.market_question || "—"}</td>
                    <td className="text-center px-3 py-2">
                      <span className="px-2 py-0.5 rounded text-xs font-bold"
                        style={{
                          background: t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                          color: t.direction === "YES" ? "var(--green)" : "var(--red)",
                        }}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="text-right px-3 py-2">${Number(t.entry_price)?.toFixed(3)}</td>
                    <td className="text-right px-3 py-2">{t.exit_price ? `$${Number(t.exit_price).toFixed(3)}` : "—"}</td>
                    <td className="text-right px-3 py-2">{t.position_usd ? `$${Number(t.position_usd).toFixed(2)}` : "—"}</td>
                    <td className="text-right px-3 py-2 font-medium" style={{ color: pnlColor(t.pnl_usd) }}>
                      {t.pnl_usd != null ? formatPnl(t.pnl_usd) : <span style={{ color: "var(--text-secondary)" }}>open</span>}
                    </td>
                    <td className="text-right px-3 py-2" style={{ color: pnlColor(t.pnl_pct) }}>
                      {t.pnl_pct != null ? formatPct(t.pnl_pct * 100) : "—"}
                    </td>
                    <td className="text-right px-3 py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {t.close_reason ?? <span style={{ color: COLORS.blue }}>OPEN</span>}
                    </td>
                    <td className="text-right px-5 py-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {t.blocked_reason?.split(" ")[0] ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function ExportButton({ trades }: { trades: any[] }) {
  const handleExport = () => {
    if (!trades.length) return;
    const headers = ["Date", "Market", "Direction", "Entry", "Exit", "Size", "PnL", "PnL%", "Reason"];
    const rows = trades.map((t) => [
      (t.closed_at ?? t.opened_at)?.slice(0, 16),
      `"${(t.market_question ?? "").replace(/"/g, '""')}"`,
      t.direction,
      t.entry_price?.toFixed(4),
      t.exit_price?.toFixed(4) ?? "",
      t.position_usd?.toFixed(2),
      (t.pnl_usd ?? 0).toFixed(2),
      ((t.pnl_pct ?? 0) * 100).toFixed(2),
      t.close_reason ?? "",
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button onClick={handleExport}
      className="px-3 py-1 rounded-md text-xs border transition-colors hover:opacity-80"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
      Export CSV
    </button>
  );
}
