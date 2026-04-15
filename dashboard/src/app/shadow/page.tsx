"use client";

import { useCallback } from "react";
import KpiCard from "@/components/KpiCard";
import { formatPnl, pnlColor, useAutoRefresh } from "@/lib/hooks";
import { useStrategy } from "@/lib/strategy-context";

type StatsResponse = {
  strategy: string;
  totalTrades: number;
  wins: number;
  losses: number;
  avgWin: number;
  avgLoss: number;
  equityCurve: { date: string; pnl: number; trade_pnl: number }[];
};

type PortfolioRow = {
  strategy: string;
  is_shadow: boolean;
  initial_capital: number | null;
  current_capital: number | null;
  total_pnl: number | null;
  win_rate: number | null;
  open_positions: number | null;
  total_trades: number | null;
} | null;

/**
 * /shadow — side-by-side Real vs Shadow comparison for the current strategy + run.
 *
 * Real = executed trades after risk gates, circuit breakers, and sizing.
 * Shadow = pure signal quality, fixed $100 per trade, no risk filter.
 * "Pure" columns on shadow rows represent the same trades if stops/TP were
 * disabled and positions were held to resolution (bot's raw edge).
 */
export default function ShadowComparePage() {
  const { strategy, runId } = useStrategy();
  const baseParams = new URLSearchParams({ strategy });
  if (runId) baseParams.set("run_id", runId);

  const portfolioFetcher = useCallback(() => {
    const p = new URLSearchParams(baseParams);
    p.set("shadow", "BOTH");
    return fetch(`/api/portfolio?${p.toString()}`).then((r) => r.json());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, runId]);
  const { data: portfolio } = useAutoRefresh<{
    real: PortfolioRow;
    shadow: PortfolioRow;
    both: boolean;
  }>(portfolioFetcher);

  const realStatsFetcher = useCallback(() => {
    const p = new URLSearchParams(baseParams);
    p.set("shadow", "REAL");
    return fetch(`/api/stats?${p.toString()}`).then((r) => r.json());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, runId]);
  const { data: realStats } = useAutoRefresh<StatsResponse>(realStatsFetcher);

  const shadowStatsFetcher = useCallback(() => {
    const p = new URLSearchParams(baseParams);
    p.set("shadow", "SHADOW");
    return fetch(`/api/stats?${p.toString()}`).then((r) => r.json());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, runId]);
  const { data: shadowStats } = useAutoRefresh<StatsResponse>(shadowStatsFetcher);

  const real = portfolio?.real ?? null;
  const shadow = portfolio?.shadow ?? null;

  return (
    <div className="space-y-6 max-w-7xl">
      <div>
        <h2 className="text-xl font-bold">{strategy} — Real vs Shadow</h2>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          Real applies risk gates and sizing. Shadow uses fixed $100 and bypasses
          all filters — it measures the pure signal quality of this run.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PortfolioColumn
          title="Real"
          row={real}
          stats={realStats}
          accent="var(--blue)"
        />
        <PortfolioColumn
          title="Shadow"
          row={shadow}
          stats={shadowStats}
          accent="var(--green)"
        />
      </div>

      <ComparisonSummary real={real} shadow={shadow} realStats={realStats} shadowStats={shadowStats} />
    </div>
  );
}

function PortfolioColumn({
  title,
  row,
  stats,
  accent,
}: {
  title: string;
  row: PortfolioRow;
  stats: StatsResponse | null | undefined;
  accent: string;
}) {
  const initial = Number(row?.initial_capital ?? 0);
  const current = Number(row?.current_capital ?? 0);
  const pnl = Number(row?.total_pnl ?? 0);
  const winRate = Number(row?.win_rate ?? 0);

  return (
    <div
      className="rounded-xl p-5 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center gap-2 mb-4">
        <span className="w-2.5 h-2.5 rounded-full" style={{ background: accent }} />
        <h3 className="text-sm font-bold">{title}</h3>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <KpiCard
          label="Capital"
          value={`$${current.toFixed(2)}`}
          subValue={`of $${initial.toFixed(0)}`}
        />
        <KpiCard
          label="Total PnL"
          value={formatPnl(pnl)}
          color={pnl >= 0 ? "green" : "red"}
        />
        <KpiCard
          label="Win Rate"
          value={`${(winRate * 100).toFixed(0)}%`}
          subValue={stats ? `${stats.wins}W / ${stats.losses}L` : undefined}
        />
        <KpiCard
          label="Trades"
          value={String(stats?.totalTrades ?? row?.total_trades ?? 0)}
          subValue={`${row?.open_positions ?? 0} open`}
        />
      </div>
    </div>
  );
}

function ComparisonSummary({
  real,
  shadow,
  realStats,
  shadowStats,
}: {
  real: PortfolioRow;
  shadow: PortfolioRow;
  realStats: StatsResponse | null | undefined;
  shadowStats: StatsResponse | null | undefined;
}) {
  if (!real && !shadow) return null;

  const realPnl = Number(real?.total_pnl ?? 0);
  const shadowPnl = Number(shadow?.total_pnl ?? 0);
  const gap = shadowPnl - realPnl;

  const realCount = realStats?.totalTrades ?? 0;
  const shadowCount = shadowStats?.totalTrades ?? 0;
  const gateDrop = shadowCount > 0 ? 1 - realCount / shadowCount : 0;

  return (
    <div
      className="rounded-xl p-5 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
        Signal Quality Gap
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            PnL gap (Shadow − Real)
          </p>
          <p className="text-xl font-bold" style={{ color: pnlColor(gap) }}>
            {formatPnl(gap)}
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            {gap > 0
              ? "Shadow outperforms — risk gates may be too tight."
              : gap < 0
                ? "Real outperforms — gates are earning their keep."
                : "Matched."}
          </p>
        </div>
        <div>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Trades executed
          </p>
          <p className="text-xl font-bold">
            {realCount}
            <span
              className="text-base ml-1"
              style={{ color: "var(--text-secondary)" }}
            >
              / {shadowCount} signals
            </span>
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            {(gateDrop * 100).toFixed(0)}% dropped by risk layer
          </p>
        </div>
        <div>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Avg PnL per signal
          </p>
          <p className="text-xl font-bold">
            Real {formatPnl(realCount > 0 ? realPnl / realCount : 0)}
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            Shadow {formatPnl(shadowCount > 0 ? shadowPnl / shadowCount : 0)}
          </p>
        </div>
      </div>
    </div>
  );
}
