"use client";

import { useState, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import KpiCard from "@/components/KpiCard";
import TimeFilterBar from "@/components/TimeFilter";
import LlmToggle from "@/components/LlmToggle";
import { useAutoRefresh, formatPnl, formatPct, pnlColor, timeAgo, getDateFromFilter } from "@/lib/hooks";
import type { TimeFilter, PortfolioState } from "@/lib/types";

export default function DashboardPage() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("1w");

  const portfolioFetcher = useCallback(() =>
    fetch("/api/portfolio").then((r) => r.json()), []);
  const { data: portfolio } = useAutoRefresh<PortfolioState>(portfolioFetcher);

  const positionsFetcher = useCallback(() =>
    fetch("/api/positions").then((r) => r.json()), []);
  const { data: positions } = useAutoRefresh<any[]>(positionsFetcher);

  const tradesFetcher = useCallback(() => {
    const since = getDateFromFilter(timeFilter);
    const params = new URLSearchParams({ status: "CLOSED", limit: "50" });
    if (since) params.set("since", since);
    return fetch(`/api/trades?${params}`).then((r) => r.json());
  }, [timeFilter]);
  const { data: trades } = useAutoRefresh<any[]>(tradesFetcher);

  // All-time trades for the equity curve (independent of time filter)
  const allTradesFetcher = useCallback(() =>
    fetch("/api/trades?status=CLOSED&limit=500").then((r) => r.json()), []);
  const { data: allTrades } = useAutoRefresh<any[]>(allTradesFetcher);

  const signalsFetcher = useCallback(() =>
    fetch("/api/signals?status=ACTIVE&limit=10").then((r) => r.json()), []);
  const { data: signals } = useAutoRefresh<any[]>(signalsFetcher);

  // Build equity curve from ALL closed trades — last point matches portfolio.total_pnl
  const equityCurve = (() => {
    if (!allTrades?.length) return [];
    let cum = 0;
    return allTrades
      .slice()
      .sort((a: any, b: any) => {
        const da = new Date(a.closed_at ?? a.opened_at).getTime();
        const db = new Date(b.closed_at ?? b.opened_at).getTime();
        return da - db;
      })
      .map((t: any) => {
        cum += t.pnl_usd ?? 0;
        return {
          date: (t.closed_at ?? t.opened_at)?.slice(5, 16).replace("T", " "),
          pnl: Math.round(cum * 100) / 100,
        };
      });
  })();

  const totalUnrealized = (positions ?? []).reduce(
    (s: number, p: any) => s + (p.unrealized_pnl ?? 0), 0
  );

  // Current drawdown: capital loss from initial — this is what the risk manager checks
  const currentDrawdown = portfolio
    ? (portfolio.initial_capital - portfolio.current_capital) / portfolio.initial_capital
    : 0;

  const isCircuitBroken = portfolio?.is_circuit_broken &&
    portfolio.circuit_broken_until &&
    new Date(portfolio.circuit_broken_until) > new Date();

  const isDrawdownBreached = currentDrawdown >= 0.20;
  const isBotPaused = isCircuitBroken || isDrawdownBreached;

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Alert banners */}
      {isCircuitBroken && (
        <div className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}>
          <span className="text-lg">&#9888;</span>
          <span>
            Circuit Breaker ACTIVE — Trading paused until{" "}
            {new Date(portfolio!.circuit_broken_until!).toLocaleString()}
          </span>
        </div>
      )}

      {!isCircuitBroken && isDrawdownBreached && (
        <div className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}>
          <span className="text-lg">&#9888;</span>
          <span>
            Drawdown limit breached — {(currentDrawdown * 100).toFixed(1)}% of capital lost (limit: 20%). Trading is blocked.
          </span>
        </div>
      )}

      {!isBotPaused && currentDrawdown >= 0.15 && (
        <div className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "#ffd93d22", color: "var(--yellow)", border: "1px solid var(--yellow)" }}>
          <span className="text-lg">&#9888;</span>
          <span>
            Warning — Current drawdown at {(currentDrawdown * 100).toFixed(1)}%, approaching 20% limit
          </span>
        </div>
      )}

      {/* Header + time filter */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Dashboard</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Real-time portfolio monitoring
          </p>
        </div>
        <div className="flex items-center gap-4">
          <LlmToggle />
          <TimeFilterBar selected={timeFilter} onChange={setTimeFilter} />
        </div>
      </div>

      {/* KPI Cards */}
      {portfolio && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard
            label="Capital"
            value={`$${portfolio.current_capital.toFixed(2)}`}
            subValue={`of $${portfolio.initial_capital.toFixed(0)}`}
            color="blue"
          />
          <KpiCard
            label="Total P&L"
            value={formatPnl(portfolio.total_pnl)}
            subValue={`${formatPct(portfolio.total_pnl / portfolio.initial_capital * 100)} realized`}
            color={portfolio.total_pnl >= 0 ? "green" : "red"}
          />
          <KpiCard
            label="Win Rate"
            value={`${(portfolio.win_rate * 100).toFixed(0)}%`}
            subValue={`${portfolio.winning_trades}W / ${portfolio.losing_trades}L`}
            color="blue"
          />
          <KpiCard
            label="Total Trades"
            value={portfolio.total_trades.toString()}
            subValue={`${portfolio.open_positions} open / ${portfolio.max_open_positions} max`}
          />
          <KpiCard
            label="Drawdown"
            value={`${(currentDrawdown * 100).toFixed(1)}%`}
            subValue="limit: 20%"
            color={currentDrawdown >= 0.20 ? "red" : currentDrawdown >= 0.15 ? "red" : "default"}
          />
          <KpiCard
            label="Loss Streak"
            value={portfolio.consecutive_losses > 0 ? `${portfolio.consecutive_losses}L` : "—"}
            subValue={portfolio.consecutive_losses >= 3 ? "CB triggered" : `CB at 3`}
            color={portfolio.consecutive_losses >= 3 ? "red" : portfolio.consecutive_losses >= 2 ? "red" : "default"}
          />
        </div>
      )}

      {/* Equity Curve */}
      {equityCurve.length > 0 && (
        <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>
            Equity Curve (Realized P&L)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={equityCurve}>
              <defs>
                <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--blue)" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="var(--blue)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "var(--text-secondary)" }}
                formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Cumulative P&L"]}
              />
              <Area type="monotone" dataKey="pnl" stroke="var(--blue)" fill="url(#pnlGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Open Positions */}
      <div className="rounded-xl border overflow-hidden" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <div className="px-5 py-3 border-b flex items-center justify-between"
          style={{ borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium">Open Positions</h3>
          <span className="text-xs px-2 py-0.5 rounded-full"
            style={{ background: "var(--blue)", color: "#fff" }}>
            {positions?.length ?? 0} / {portfolio?.max_open_positions ?? 5}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                <th className="text-left px-5 py-2 font-medium">Market</th>
                <th className="text-center px-3 py-2 font-medium">Side</th>
                <th className="text-right px-3 py-2 font-medium">Entry</th>
                <th className="text-right px-3 py-2 font-medium">Current</th>
                <th className="text-right px-3 py-2 font-medium">P&L</th>
                <th className="text-right px-3 py-2 font-medium">P&L %</th>
                <th className="text-right px-5 py-2 font-medium">Held</th>
              </tr>
            </thead>
            <tbody>
              {(positions ?? []).map((p: any) => (
                <tr key={p.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-5 py-2.5 max-w-64 truncate">{p.market_question}</td>
                  <td className="text-center px-3 py-2.5">
                    <span className="px-2 py-0.5 rounded text-xs font-bold"
                      style={{
                        background: p.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                        color: p.direction === "YES" ? "var(--green)" : "var(--red)",
                      }}>
                      {p.direction}
                    </span>
                  </td>
                  <td className="text-right px-3 py-2.5">${p.entry_price.toFixed(3)}</td>
                  <td className="text-right px-3 py-2.5">${p.current_price.toFixed(3)}</td>
                  <td className="text-right px-3 py-2.5 font-medium" style={{ color: pnlColor(p.unrealized_pnl) }}>
                    {formatPnl(p.unrealized_pnl)}
                  </td>
                  <td className="text-right px-3 py-2.5" style={{ color: pnlColor(p.unrealized_pnl_pct) }}>
                    {formatPct(p.unrealized_pnl_pct)}
                  </td>
                  <td className="text-right px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                    {timeAgo(p.opened_at)}
                  </td>
                </tr>
              ))}
              {(positions ?? []).length === 0 && (
                <tr><td colSpan={7} className="px-5 py-8 text-center" style={{ color: "var(--text-secondary)" }}>No open positions</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {positions && positions.length > 0 && (
          <div className="px-5 py-2.5 border-t flex justify-end text-sm font-medium"
            style={{ borderColor: "var(--border)" }}>
            <span style={{ color: "var(--text-secondary)" }}>Total Unrealized:&nbsp;</span>
            <span style={{ color: pnlColor(totalUnrealized) }}>{formatPnl(totalUnrealized)}</span>
          </div>
        )}
      </div>

      {/* Active Signals */}
      {signals && signals.length > 0 && (
        <div className="rounded-xl border overflow-hidden" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
          <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
            <h3 className="text-sm font-medium">Active Signals (pending execution)</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left px-5 py-2 font-medium">Market</th>
                  <th className="text-center px-3 py-2 font-medium">Dir</th>
                  <th className="text-right px-3 py-2 font-medium">Score</th>
                  <th className="text-right px-3 py-2 font-medium">Price</th>
                  <th className="text-right px-5 py-2 font-medium">Age</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s: any) => (
                  <tr key={s.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-5 py-2.5 max-w-64 truncate">{s.market_question}</td>
                    <td className="text-center px-3 py-2.5">
                      <span className="px-2 py-0.5 rounded text-xs font-bold"
                        style={{
                          background: s.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                          color: s.direction === "YES" ? "var(--green)" : "var(--red)",
                        }}>
                        {s.direction}
                      </span>
                    </td>
                    <td className="text-right px-3 py-2.5">{s.total_score.toFixed(1)}</td>
                    <td className="text-right px-3 py-2.5">${s.price_at_signal?.toFixed(3)}</td>
                    <td className="text-right px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                      {timeAgo(s.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent Trades */}
      <div className="rounded-xl border overflow-hidden" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium">Recent Trades</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                <th className="text-left px-5 py-2 font-medium">Date</th>
                <th className="text-left px-3 py-2 font-medium">Market</th>
                <th className="text-center px-3 py-2 font-medium">Side</th>
                <th className="text-right px-3 py-2 font-medium">Entry</th>
                <th className="text-right px-3 py-2 font-medium">Exit</th>
                <th className="text-right px-3 py-2 font-medium">P&L</th>
                <th className="text-right px-3 py-2 font-medium">Return</th>
                <th className="text-right px-5 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {(trades ?? []).map((t: any) => (
                <tr key={t.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-5 py-2.5 whitespace-nowrap" style={{ color: "var(--text-secondary)" }}>
                    {(t.closed_at ?? t.opened_at)?.slice(5, 16).replace("T", " ")}
                  </td>
                  <td className="px-3 py-2.5 max-w-48 truncate">{t.market_question}</td>
                  <td className="text-center px-3 py-2.5">
                    <span className="px-2 py-0.5 rounded text-xs font-bold"
                      style={{
                        background: t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                        color: t.direction === "YES" ? "var(--green)" : "var(--red)",
                      }}>
                      {t.direction}
                    </span>
                  </td>
                  <td className="text-right px-3 py-2.5">${t.entry_price?.toFixed(3)}</td>
                  <td className="text-right px-3 py-2.5">{t.exit_price ? `$${t.exit_price.toFixed(3)}` : "—"}</td>
                  <td className="text-right px-3 py-2.5 font-medium" style={{ color: pnlColor(t.pnl_usd) }}>
                    {formatPnl(t.pnl_usd)}
                  </td>
                  <td className="text-right px-3 py-2.5" style={{ color: pnlColor(t.pnl_pct) }}>
                    {formatPct((t.pnl_pct ?? 0) * 100)}
                  </td>
                  <td className="text-right px-5 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {t.close_reason ?? "—"}
                  </td>
                </tr>
              ))}
              {(trades ?? []).length === 0 && (
                <tr><td colSpan={8} className="px-5 py-8 text-center" style={{ color: "var(--text-secondary)" }}>No trades in this period</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
