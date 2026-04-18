"use client";

// Mirrors src/strategies/common/config.py MAX_DRAWDOWN_PCT
const C_MAX_DRAWDOWN_PCT = 0.30;

import { useCallback, useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import KpiCard from "@/components/KpiCard";
import TimeFilterBar from "@/components/TimeFilter";
import {
  computeEV,
  formatClosesAt,
  formatPct,
  formatPnl,
  getDateFromFilter,
  pnlColor,
  prefetchIntoCache,
  timeAgo,
  useAutoRefresh,
} from "@/lib/hooks";
import { ctxQueryString, useStrategy } from "@/lib/strategy-context";
import type { PortfolioState, TimeFilter } from "@/lib/types";

export default function DashboardPage() {
  const { strategy, runId, shadowMode } = useStrategy();
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("1w");
  const [toggling, setToggling] = useState(false);
  const ctx = ctxQueryString(strategy, runId, shadowMode);

  const portfolioFetcher = useCallback(
    () =>
      fetch(`/api/portfolio?${ctx}`)
        .then((r) => r.json())
        .then((p) => (p && p.both ? p.real ?? p.shadow : p)),
    [ctx],
  );
  const { data: portfolio, refresh: refreshPortfolio } =
    useAutoRefresh<PortfolioState>(portfolioFetcher, 60000, `portfolio:${ctx}`);

  const positionsFetcher = useCallback(
    () => fetch(`/api/positions?${ctx}`).then((r) => r.json()),
    [ctx],
  );
  const { data: positions } = useAutoRefresh<Record<string, unknown>[]>(
    positionsFetcher,
    60000,
    `positions:${ctx}`,
  );

  const tradesFetcher = useCallback(() => {
    const since = getDateFromFilter(timeFilter);
    const params = new URLSearchParams(ctx);
    params.set("status", "CLOSED");
    params.set("limit", "50");
    if (since) params.set("since", since);
    return fetch(`/api/trades?${params}`).then((r) => r.json());
  }, [ctx, timeFilter]);
  const { data: trades } = useAutoRefresh<Record<string, unknown>[]>(
    tradesFetcher,
    60000,
    `trades:${ctx}:${timeFilter}`,
  );

  const allTradesFetcher = useCallback(
    // Equity curve only uses pnl_usd + close/open timestamps. limit=100 keeps
    // payload under ~20 KB; the underlying endpoint caps at 200 anyway.
    () => fetch(`/api/trades?${ctx}&status=CLOSED&limit=100`).then((r) => r.json()),
    [ctx],
  );
  // Equity curve updates much less often than portfolio — poll every 5 min.
  const { data: rawAllTrades } = useAutoRefresh<Record<string, unknown>[]>(
    allTradesFetcher,
    300000,
    `equity:${ctx}`,
  );

  // ── Prefetch both strategies' portfolio+positions in the background so the
  // first strategy switch is instant (the cache is already warm). Runs once
  // per shadowMode change. Only fires after the current context has been
  // resolved to avoid clashing with the primary fetches above.
  useEffect(() => {
    const strategies: ("SPECIALIST" | "SCALPER")[] = ["SPECIALIST", "SCALPER"];
    const timer = setTimeout(() => {
      for (const s of strategies) {
        const otherCtx = ctxQueryString(s, null, shadowMode);
        prefetchIntoCache(`portfolio:${otherCtx}`, () =>
          fetch(`/api/portfolio?${otherCtx}`)
            .then((r) => r.json())
            .then((p) => (p && p.both ? p.real ?? p.shadow : p)),
        );
        prefetchIntoCache(`positions:${otherCtx}`, () =>
          fetch(`/api/positions?${otherCtx}`).then((r) => r.json()),
        );
      }
    }, 800); // after the primary fetches settle
    return () => clearTimeout(timer);
  }, [shadowMode]);

  const equityCurve = (() => {
    const list = rawAllTrades ?? [];
    if (list.length === 0) return [];
    const sorted = list
      .slice()
      .sort((a, b) => {
        const da = new Date((a.closed_at as string) ?? (a.opened_at as string)).getTime();
        const db = new Date((b.closed_at as string) ?? (b.opened_at as string)).getTime();
        return da - db;
      });
    let cum = 0;
    return sorted.map((t) => {
      cum += Number(t.pnl_usd ?? 0);
      const stamp = (t.closed_at as string) ?? (t.opened_at as string) ?? "";
      return {
        date: stamp.slice(5, 16).replace("T", " "),
        pnl: Math.round(cum * 100) / 100,
      };
    });
  })();


  const totalUnrealized = (positions ?? []).reduce(
    (s, p) => s + Number(p.unrealized_pnl ?? 0),
    0,
  );

  const initial = Number(portfolio?.initial_capital ?? 0);
  const current = Number(portfolio?.current_capital ?? 0);
  // ATH-based drawdown: use peak_capital (high-water mark) instead of initial_capital.
  const peak = Number(portfolio?.peak_capital ?? portfolio?.initial_capital ?? 0);
  const currentDrawdown = peak > 0 ? Math.max(0, (peak - current) / peak) : 0;

  const isCircuitBroken =
    portfolio?.is_circuit_broken &&
    (portfolio.requires_manual_review ||
      (portfolio.circuit_broken_until &&
        new Date(portfolio.circuit_broken_until) > new Date()));

  const isManualStop =
    portfolio?.is_circuit_broken && portfolio?.requires_manual_review;

  // Auto-tripped = CB active AND has a future timer (set by consecutive-loss logic).
  // Manual stop = CB active with requires_manual_review but no future timer.
  const isAutoTripped =
    isCircuitBroken &&
    !!(portfolio?.circuit_broken_until) &&
    new Date(portfolio!.circuit_broken_until!) > new Date();

  const isDrawdownBreached = currentDrawdown >= C_MAX_DRAWDOWN_PCT;
  const isBotPaused = isCircuitBroken || isDrawdownBreached;

  // ── Bot control toggle ────────────────────────────────────────────────
  async function toggleBot() {
    if (toggling) return;
    setToggling(true);
    const action = portfolio?.is_circuit_broken ? "resume" : "pause";
    try {
      const params = new URLSearchParams();
      params.set("strategy", strategy);
      if (runId) params.set("run_id", runId);
      await fetch(`/api/bot-control?${params}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      await refreshPortfolio();
    } finally {
      setToggling(false);
    }
  }

  const botIsPaused = portfolio?.is_circuit_broken ?? false;

  return (
    <div className="space-y-6 max-w-7xl">
      {/* ── Auto circuit breaker alert ── */}
      {isAutoTripped && (
        <div
          className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}
        >
          <span className="text-lg">&#9888;</span>
          <span>
            Circuit Breaker ACTIVE — {portfolio!.consecutive_losses ?? 0} consecutive losses.
            Paused until {portfolio!.circuit_broken_until
              ? new Date(portfolio!.circuit_broken_until).toLocaleString()
              : "—"}.
            {" "}Manual review required before resuming.
          </span>
        </div>
      )}

      {/* ── Manual stop alert ── */}
      {isManualStop && !isAutoTripped && (
        <div
          className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "#f97316" + "22", color: "#f97316", border: "1px solid #f97316" }}
        >
          <span className="text-lg">&#9646;&#9646;</span>
          <span>Bot manually paused — click Resume to re-enable trading.</span>
        </div>
      )}

      {/* ── Drawdown warning ── */}
      {!isBotPaused && currentDrawdown >= 0.15 && (
        <div
          className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "#ffd93d22", color: "var(--yellow)", border: "1px solid var(--yellow)" }}
        >
          <span className="text-lg">&#9888;</span>
          <span>
            Warning — drawdown {(currentDrawdown * 100).toFixed(1)}% from ATH, approaching 30% limit.
          </span>
        </div>
      )}

      {/* ── Drawdown breached ── */}
      {isDrawdownBreached && !isCircuitBroken && (
        <div
          className="rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2"
          style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}
        >
          <span className="text-lg">&#9888;</span>
          <span>
            Drawdown limit breached — {(currentDrawdown * 100).toFixed(1)}% from ATH (limit 30%). Trading blocked.
          </span>
        </div>
      )}

      {/* ── Header row: title + bot toggle button ── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">{strategy} Dashboard</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Paper-mode copytrading — live metrics
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Bot status pill */}
          <span
            className="text-xs font-bold px-3 py-1 rounded-full"
            style={
              botIsPaused
                ? { background: "var(--red-dim)", color: "var(--red)" }
                : { background: "var(--green-dim)", color: "var(--green)" }
            }
          >
            {botIsPaused ? "PAUSED" : "RUNNING"}
          </span>

          {/* Toggle button */}
          <button
            onClick={toggleBot}
            disabled={toggling}
            className="text-sm font-semibold px-4 py-1.5 rounded-lg transition-opacity disabled:opacity-50"
            style={
              botIsPaused
                ? {
                    background: "var(--green)",
                    color: "#fff",
                    border: "none",
                    cursor: toggling ? "not-allowed" : "pointer",
                  }
                : {
                    background: "var(--red)",
                    color: "#fff",
                    border: "none",
                    cursor: toggling ? "not-allowed" : "pointer",
                  }
            }
          >
            {toggling ? "..." : botIsPaused ? "Resume Bot" : "Pause Bot"}
          </button>

          <TimeFilterBar selected={timeFilter} onChange={setTimeFilter} />
        </div>
      </div>

      {portfolio && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard
            label="Capital"
            value={`$${current.toFixed(2)}`}
            subValue={`ATH $${peak.toFixed(0)}`}
            color="blue"
          />
          <KpiCard
            label="Realized P&L"
            value={formatPnl(Number(portfolio.total_pnl ?? 0))}
            subValue={
              initial > 0
                ? `${formatPct((Number(portfolio.total_pnl ?? 0) / initial) * 100)} of capital`
                : ""
            }
            color={Number(portfolio.total_pnl ?? 0) >= 0 ? "green" : "red"}
          />
          <KpiCard
            label="Win Rate"
            value={`${(Number(portfolio.win_rate ?? 0) * 100).toFixed(0)}%`}
            subValue={`${portfolio.winning_trades ?? 0}W / ${portfolio.losing_trades ?? 0}L`}
            color="blue"
          />
          <KpiCard
            label="Total Trades"
            value={String(portfolio.total_trades ?? 0)}
            subValue={`${portfolio.open_positions ?? 0} open / ${portfolio.max_open_positions ?? 0} max`}
          />
          <KpiCard
            label="Drawdown"
            value={`${(currentDrawdown * 100).toFixed(1)}%`}
            subValue="from ATH · limit 30%"
            color={currentDrawdown >= 0.2 ? "red" : currentDrawdown >= 0.15 ? "red" : "default"}
          />
          <KpiCard
            label="Loss Streak"
            value={Number(portfolio.consecutive_losses ?? 0) > 0 ? `${portfolio.consecutive_losses}L` : "—"}
            subValue={Number(portfolio.consecutive_losses ?? 0) >= 3 ? "CB triggered" : "CB at 3"}
            color={Number(portfolio.consecutive_losses ?? 0) >= 3 ? "red" : "default"}
          />
        </div>
      )}

      {equityCurve.length > 0 && (
        <div
          className="rounded-xl p-5 border"
          style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
        >
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
                contentStyle={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{ color: "var(--text-secondary)" }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, "Cumulative P&L"]}
              />
              <Area type="monotone" dataKey="pnl" stroke="var(--blue)" fill="url(#pnlGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <div
          className="px-5 py-3 border-b flex items-center justify-between"
          style={{ borderColor: "var(--border)" }}
        >
          <h3 className="text-sm font-medium">Open Positions</h3>
          <span
            className="text-xs px-2 py-0.5 rounded-full"
            style={{ background: "var(--blue)", color: "#fff" }}
          >
            {positions?.length ?? 0} / {portfolio?.max_open_positions ?? 0}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr
                style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}
              >
                <th className="text-left px-5 py-2 font-medium">Market</th>
                <th className="text-center px-3 py-2 font-medium">Side</th>
                {shadowMode === "BOTH" && (
                  <th className="text-center px-3 py-2 font-medium">Type</th>
                )}
                {strategy !== "SCALPER" && (
                  <th className="text-center px-3 py-2 font-medium">Signal</th>
                )}
                <th className="text-right px-3 py-2 font-medium">Size</th>
                <th className="text-right px-3 py-2 font-medium">Entry</th>
                {strategy !== "SCALPER" && (
                  <th className="text-center px-3 py-2 font-medium" title="Specialists in favor / against">Specs</th>
                )}
                <th className="text-right px-3 py-2 font-medium" title="Average historical hit rate of signaling specialists">Avg HR</th>
                <th className="text-right px-3 py-2 font-medium" title="EV = avg hit rate − entry price · positive = odds on your side">EV</th>
                <th className="text-right px-3 py-2 font-medium">SL / TP</th>
                <th className="text-right px-3 py-2 font-medium">Unrealized</th>
                <th className="text-right px-3 py-2 font-medium">Closes</th>
                <th className="text-right px-5 py-2 font-medium">Held</th>
              </tr>
            </thead>
            <tbody>
              {(positions ?? []).map((p) => {
                const meta = (p.metadata ?? {}) as Record<string, unknown>;
                const quality = String(meta.signal_quality ?? "");
                const universe = String(meta.universe ?? "");
                const isShadow = p.is_shadow === true;
                const entry = Number(p.entry_price ?? 0);
                const sl = entry > 0 ? Math.max(entry * 0.85, 0.001) : null;
                // Binary market prices ∈ [0, 1]: cap TP at 0.999 (resolves at 1.0)
                const tp = entry > 0 ? Math.min(entry * 1.20, 0.999) : null;
                const trailingActive = meta.trailing_active === true;
                const hwm = meta.high_water_mark != null ? Number(meta.high_water_mark) : null;
                const specsFor = meta.specialists_count != null ? Number(meta.specialists_count) : null;
                const specsAgainst = meta.specialists_against != null ? Number(meta.specialists_against) : null;
                const avgHr = meta.avg_hit_rate != null ? Number(meta.avg_hit_rate) : null;
                const ev = computeEV(avgHr, entry);
                const closesAt = meta.closes_at as string | undefined;
                return (
                  <tr key={String(p.id)} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-5 py-2.5 max-w-56 truncate" title={String(p.market_question ?? "")}>
                      {String(p.market_question ?? "")}
                    </td>
                    <td className="text-center px-3 py-2.5">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-bold"
                        style={{
                          background: p.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                          color: p.direction === "YES" ? "var(--green)" : "var(--red)",
                        }}
                      >
                        {String(p.direction ?? "")}
                      </span>
                    </td>
                    {shadowMode === "BOTH" && (
                      <td className="text-center px-3 py-2.5">
                        <span
                          className="px-2 py-0.5 rounded text-xs font-bold"
                          style={
                            isShadow
                              ? { background: "#ffffff18", color: "var(--text-secondary)" }
                              : { background: "#3b82f622", color: "#3b82f6" }
                          }
                        >
                          {isShadow ? "SHADOW" : "REAL"}
                        </span>
                      </td>
                    )}
                    {strategy !== "SCALPER" && (
                      <td className="text-center px-3 py-2.5">
                        {quality ? (
                          <span
                            className="px-1.5 py-0.5 rounded text-xs font-bold"
                            title={universe}
                            style={
                              quality === "CLEAN"
                                ? { background: "var(--green-dim)", color: "var(--green)" }
                                : quality === "CONTESTED"
                                ? { background: "#ffd93d22", color: "var(--yellow)" }
                                : { background: "var(--bg-secondary)", color: "var(--text-secondary)" }
                            }
                          >
                            {quality}
                          </span>
                        ) : (
                          <span style={{ color: "var(--text-secondary)" }}>—</span>
                        )}
                      </td>
                    )}
                    <td className="text-right px-3 py-2.5 font-medium">
                      ${Number(p.position_usd ?? 0).toFixed(2)}
                    </td>
                    <td className="text-right px-3 py-2.5">
                      ${entry.toFixed(3)}
                    </td>
                    {strategy !== "SCALPER" && (
                      <td className="text-center px-3 py-2.5 text-xs">
                        {specsFor != null ? (
                          <span>
                            <span style={{ color: "var(--green)" }}>{specsFor}</span>
                            <span style={{ color: "var(--text-secondary)" }}>{" / "}</span>
                            <span style={{ color: "var(--red)" }}>{specsAgainst ?? 0}</span>
                          </span>
                        ) : (
                          <span style={{ color: "var(--text-secondary)" }}>—</span>
                        )}
                      </td>
                    )}
                    <td className="text-right px-3 py-2.5 text-xs">
                      {avgHr != null ? `${(avgHr * 100).toFixed(0)}%` : <span style={{ color: "var(--text-secondary)" }}>—</span>}
                    </td>
                    <td
                      className="text-right px-3 py-2.5 font-medium text-xs"
                      style={{ color: ev != null ? pnlColor(ev) : "var(--text-secondary)" }}
                      title={ev != null ? `Expected value per $1 staked: ${ev >= 0 ? "+" : ""}$${ev.toFixed(3)}` : undefined}
                    >
                      {ev != null ? `${ev >= 0 ? "+" : ""}${(ev * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className="text-right px-3 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {isShadow && sl != null && tp != null ? (
                        <span>
                          <span style={{ color: "var(--red)" }}>${sl.toFixed(3)}</span>
                          {" / "}
                          <span style={{ color: "var(--green)" }}>${tp.toFixed(3)}</span>
                        </span>
                      ) : !isShadow && hwm != null ? (
                        <span title="trailing stop active · high-water mark">
                          {trailingActive
                            ? <span style={{ color: "var(--green)" }}>trail ↑${hwm.toFixed(3)}</span>
                            : <span>hwm ${hwm.toFixed(3)}</span>}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td
                      className="text-right px-3 py-2.5 font-medium text-xs"
                      style={{ color: pnlColor(Number(p.unrealized_pnl ?? 0)) }}
                    >
                      {Number(p.unrealized_pnl ?? 0) !== 0
                        ? formatPnl(Number(p.unrealized_pnl ?? 0))
                        : <span style={{ color: "var(--text-secondary)" }}>—</span>}
                    </td>
                    <td className="text-right px-3 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {formatClosesAt(closesAt)}
                    </td>
                    <td className="text-right px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                      {timeAgo(p.opened_at as string)}
                    </td>
                  </tr>
                );
              })}
              {(positions ?? []).length === 0 && (
                <tr>
                  <td
                    colSpan={
                      (shadowMode === "BOTH" ? 13 : 12) - (strategy === "SCALPER" ? 2 : 0)
                    }
                    className="px-5 py-8 text-center"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    No open positions
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {positions && positions.length > 0 && (
          <div
            className="px-5 py-2.5 border-t flex justify-between items-center text-xs"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            <span>Unrealized P&L fetched live from CLOB · SL/TP are fixed stops for shadow trades</span>
            <span className="text-sm font-medium">
              <span>Total Unrealized:&nbsp;</span>
              <span style={{ color: pnlColor(totalUnrealized) }}>{formatPnl(totalUnrealized)}</span>
            </span>
          </div>
        )}
      </div>

      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
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
                {shadowMode === "BOTH" && (
                  <th className="text-center px-3 py-2 font-medium">Type</th>
                )}
                {strategy !== "SCALPER" && (
                  <th className="text-center px-3 py-2 font-medium">Signal</th>
                )}
                <th className="text-right px-3 py-2 font-medium">Size</th>
                <th className="text-right px-3 py-2 font-medium">Entry</th>
                <th className="text-right px-3 py-2 font-medium">Exit</th>
                {strategy !== "SCALPER" && (
                  <th className="text-center px-3 py-2 font-medium" title="Specialists in favor / against">Specs</th>
                )}
                <th className="text-right px-3 py-2 font-medium" title="Average historical hit rate of signaling specialists">Avg HR</th>
                <th className="text-right px-3 py-2 font-medium" title="EV = avg hit rate − entry price at open">EV</th>
                <th className="text-right px-3 py-2 font-medium">P&L</th>
                <th className="text-right px-3 py-2 font-medium">Return</th>
                <th className="text-right px-5 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {(trades ?? []).map((t) => {
                const stamp = (t.closed_at as string) ?? (t.opened_at as string) ?? "";
                const isShadow = t.is_shadow === true;
                const meta = (t.metadata ?? {}) as Record<string, unknown>;
                const quality = String(meta.signal_quality ?? "");
                const specsFor = meta.specialists_count != null ? Number(meta.specialists_count) : null;
                const specsAgainst = meta.specialists_against != null ? Number(meta.specialists_against) : null;
                const avgHr = meta.avg_hit_rate != null ? Number(meta.avg_hit_rate) : null;
                const entryPx = Number(t.entry_price ?? 0);
                const ev = computeEV(avgHr, entryPx);
                return (
                  <tr key={String(t.id)} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td
                      className="px-5 py-2.5 whitespace-nowrap"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {stamp.slice(5, 16).replace("T", " ")}
                    </td>
                    <td className="px-3 py-2.5 max-w-48 truncate" title={String(t.market_question ?? "")}>
                      {String(t.market_question ?? "")}
                    </td>
                    <td className="text-center px-3 py-2.5">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-bold"
                        style={{
                          background:
                            t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                          color: t.direction === "YES" ? "var(--green)" : "var(--red)",
                        }}
                      >
                        {String(t.direction ?? "")}
                      </span>
                    </td>
                    {shadowMode === "BOTH" && (
                      <td className="text-center px-3 py-2.5">
                        <span
                          className="px-2 py-0.5 rounded text-xs font-bold"
                          style={
                            isShadow
                              ? { background: "#ffffff18", color: "var(--text-secondary)" }
                              : { background: "#3b82f622", color: "#3b82f6" }
                          }
                        >
                          {isShadow ? "SHADOW" : "REAL"}
                        </span>
                      </td>
                    )}
                    {strategy !== "SCALPER" && (
                      <td className="text-center px-3 py-2.5">
                        {quality ? (
                          <span
                            className="px-1.5 py-0.5 rounded text-xs font-bold"
                            style={
                              quality === "CLEAN"
                                ? { background: "var(--green-dim)", color: "var(--green)" }
                                : quality === "CONTESTED"
                                ? { background: "#ffd93d22", color: "var(--yellow)" }
                                : { background: "var(--bg-secondary)", color: "var(--text-secondary)" }
                            }
                          >
                            {quality}
                          </span>
                        ) : (
                          <span style={{ color: "var(--text-secondary)" }}>—</span>
                        )}
                      </td>
                    )}
                    <td className="text-right px-3 py-2.5 font-medium">
                      ${Number(t.position_usd ?? 0).toFixed(2)}
                    </td>
                    <td className="text-right px-3 py-2.5">
                      ${entryPx.toFixed(3)}
                    </td>
                    <td className="text-right px-3 py-2.5">
                      {t.exit_price != null ? `$${Number(t.exit_price).toFixed(3)}` : "—"}
                    </td>
                    {strategy !== "SCALPER" && (
                      <td className="text-center px-3 py-2.5 text-xs">
                        {specsFor != null ? (
                          <span>
                            <span style={{ color: "var(--green)" }}>{specsFor}</span>
                            <span style={{ color: "var(--text-secondary)" }}>{" / "}</span>
                            <span style={{ color: "var(--red)" }}>{specsAgainst ?? 0}</span>
                          </span>
                        ) : (
                          <span style={{ color: "var(--text-secondary)" }}>—</span>
                        )}
                      </td>
                    )}
                    <td className="text-right px-3 py-2.5 text-xs">
                      {avgHr != null ? `${(avgHr * 100).toFixed(0)}%` : <span style={{ color: "var(--text-secondary)" }}>—</span>}
                    </td>
                    <td
                      className="text-right px-3 py-2.5 font-medium text-xs"
                      style={{ color: ev != null ? pnlColor(ev) : "var(--text-secondary)" }}
                      title={ev != null ? `EV at open per $1 staked: ${ev >= 0 ? "+" : ""}$${ev.toFixed(3)}` : undefined}
                    >
                      {ev != null ? `${ev >= 0 ? "+" : ""}${(ev * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td
                      className="text-right px-3 py-2.5 font-medium"
                      style={{ color: pnlColor(Number(t.pnl_usd ?? 0)) }}
                    >
                      {formatPnl(Number(t.pnl_usd ?? 0))}
                    </td>
                    <td
                      className="text-right px-3 py-2.5"
                      style={{ color: pnlColor(Number(t.pnl_pct ?? 0)) }}
                    >
                      {formatPct(Number(t.pnl_pct ?? 0) * 100)}
                    </td>
                    <td
                      className="text-right px-5 py-2.5 text-xs"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {String(t.close_reason ?? "—")}
                    </td>
                  </tr>
                );
              })}
              {(trades ?? []).length === 0 && (
                <tr>
                  <td
                    colSpan={
                      (shadowMode === "BOTH" ? 14 : 13) - (strategy === "SCALPER" ? 2 : 0)
                    }
                    className="px-5 py-8 text-center"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    No trades in this period
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

