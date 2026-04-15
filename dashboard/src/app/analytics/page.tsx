"use client";

import { useCallback, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import KpiCard from "@/components/KpiCard";
import TimeFilterBar from "@/components/TimeFilter";
import { formatPnl, formatPct, pnlColor, useAutoRefresh } from "@/lib/hooks";
import { useStrategy } from "@/lib/strategy-context";
import type { TimeFilter } from "@/lib/types";

type StatsResponse = {
  strategy: string;
  totalTrades: number;
  wins: number;
  losses: number;
  avgWin: number;
  avgLoss: number;
  avgHoldTimeHours: number;
  byDirection: {
    YES: { count: number; pnl: number; winRate: number };
    NO: { count: number; pnl: number; winRate: number };
  };
  byCloseReason: Record<string, { count: number; pnl: number }>;
  dailyPnl: Record<string, number>;
  equityCurve: { date: string; pnl: number; trade_pnl: number }[];
};

export default function AnalyticsPage() {
  const { strategy } = useStrategy();
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("1m");

  const statsFetcher = useCallback(
    () => fetch(`/api/stats?strategy=${strategy}`).then((r) => r.json()),
    [strategy],
  );
  const { data: stats, loading } = useAutoRefresh<StatsResponse>(statsFetcher, 30000);

  const dailyChart = Object.entries(stats?.dailyPnl ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, pnl]) => ({ date: date.slice(5), pnl: Math.round(pnl * 100) / 100 }));

  const closeReasonChart = Object.entries(stats?.byCloseReason ?? {}).map(([reason, v]) => ({
    reason,
    count: v.count,
    pnl: Math.round(v.pnl * 100) / 100,
  }));

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">{strategy} Analytics</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Realized PnL and trade distribution
          </p>
        </div>
        <TimeFilterBar selected={timeFilter} onChange={setTimeFilter} />
      </div>

      {loading && !stats && (
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading…
        </div>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Closed Trades" value={String(stats.totalTrades)} />
            <KpiCard label="Wins / Losses" value={`${stats.wins} / ${stats.losses}`} color="blue" />
            <KpiCard
              label="Avg Win / Loss"
              value={`${formatPnl(stats.avgWin)} / ${formatPnl(stats.avgLoss)}`}
            />
            <KpiCard label="Avg Hold" value={`${stats.avgHoldTimeHours}h`} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div
              className="rounded-xl p-5 border"
              style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
            >
              <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
                By Direction
              </h3>
              <div className="space-y-2 text-sm">
                <DirectionRow label="YES" {...stats.byDirection.YES} />
                <DirectionRow label="NO" {...stats.byDirection.NO} />
              </div>
            </div>

            <div
              className="rounded-xl p-5 border"
              style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
            >
              <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
                By Close Reason
              </h3>
              <div className="space-y-1 text-sm">
                {closeReasonChart.length === 0 && (
                  <div style={{ color: "var(--text-secondary)" }}>No closed trades yet.</div>
                )}
                {closeReasonChart.map((r) => (
                  <div key={r.reason} className="flex justify-between">
                    <span style={{ color: "var(--text-secondary)" }}>{r.reason}</span>
                    <span>
                      {r.count} ·{" "}
                      <span style={{ color: pnlColor(r.pnl) }}>{formatPnl(r.pnl)}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {dailyChart.length > 0 && (
            <div
              className="rounded-xl p-5 border"
              style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
            >
              <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
                Daily Realized PnL
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={dailyChart}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                  <Tooltip />
                  <Bar dataKey="pnl" fill="var(--blue)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {stats.equityCurve.length > 0 && (
            <div
              className="rounded-xl p-5 border"
              style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
            >
              <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
                Equity Curve (per trade)
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={stats.equityCurve}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="pnl"
                    stroke="var(--blue)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DirectionRow({
  label,
  count,
  pnl,
  winRate,
}: {
  label: string;
  count: number;
  pnl: number;
  winRate: number;
}) {
  return (
    <div className="flex items-center justify-between">
      <span
        className="px-2 py-0.5 rounded text-xs font-bold"
        style={{
          background: label === "YES" ? "var(--green-dim)" : "var(--red-dim)",
          color: label === "YES" ? "var(--green)" : "var(--red)",
        }}
      >
        {label}
      </span>
      <span style={{ color: "var(--text-secondary)" }}>
        {count} trades · WR {winRate}% ·{" "}
        <span style={{ color: pnlColor(pnl) }}>{formatPnl(pnl)}</span>
      </span>
      <span className="sr-only">{formatPct(winRate)}</span>
    </div>
  );
}
