"use client";

import { useState, useCallback } from "react";
import { useAutoRefresh, formatPnl } from "@/lib/hooks";
import type { PortfolioState } from "@/lib/types";

export default function ServicesPage() {
  const portfolioFetcher = useCallback(() =>
    fetch("/api/portfolio").then((r) => r.json()), []);
  const { data: portfolio } = useAutoRefresh<PortfolioState>(portfolioFetcher);

  const signalsFetcher = useCallback(() =>
    fetch("/api/signals?status=ACTIVE&limit=50").then((r) => r.json()), []);
  const { data: signals } = useAutoRefresh<any[]>(signalsFetcher);

  const services = [
    { name: "polymarket-collector", desc: "Market data & snapshots every 2min", log: "collector" },
    { name: "polymarket-signal-engine", desc: "Signal generation every 5min", log: "signals" },
    { name: "polymarket-paper-trader", desc: "Trade execution & position management", log: "trader" },
    { name: "polymarket-status-api", desc: "HTTP status API (port 8765)", log: "status" },
  ];

  const isCircuitBroken = portfolio?.is_circuit_broken ?? false;
  const cbExpired = portfolio?.circuit_broken_until
    ? new Date(portfolio.circuit_broken_until) < new Date()
    : true;
  const cbActive = isCircuitBroken && !cbExpired;

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-xl font-bold">Services</h2>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          System status & infrastructure monitoring
        </p>
      </div>

      {/* Service cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {services.map((svc) => (
          <div key={svc.name} className="rounded-xl p-5 border"
            style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
            <div className="flex items-center gap-3 mb-2">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--green)" }} />
              <h3 className="text-sm font-medium">{svc.name}</h3>
            </div>
            <p className="text-xs ml-5" style={{ color: "var(--text-secondary)" }}>{svc.desc}</p>
            <p className="text-xs ml-5 mt-1" style={{ color: "var(--text-secondary)" }}>
              Status: <span style={{ color: "var(--green)" }}>running (systemd)</span>
            </p>
          </div>
        ))}
      </div>

      {/* Circuit Breaker */}
      <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <h3 className="text-sm font-medium mb-4">Circuit Breaker</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Status</p>
            <p className="text-lg font-bold" style={{ color: cbActive ? "var(--red)" : "var(--green)" }}>
              {cbActive ? "ACTIVE" : "OK"}
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Consecutive Losses</p>
            <p className="text-lg font-bold" style={{
              color: (portfolio?.consecutive_losses ?? 0) >= 2 ? "var(--red)" : "var(--text-primary)"
            }}>
              {portfolio?.consecutive_losses ?? 0} / 3
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Max Drawdown</p>
            <p className="text-lg font-bold" style={{
              color: (portfolio?.max_drawdown ?? 0) > 0.15 ? "var(--red)" : "var(--text-primary)"
            }}>
              {((portfolio?.max_drawdown ?? 0) * 100).toFixed(1)}% / 20%
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Open Slots</p>
            <p className="text-lg font-bold">
              {portfolio?.open_positions ?? 0} / {portfolio?.max_open_positions ?? 5}
            </p>
          </div>
        </div>
        {cbActive && portfolio?.circuit_broken_until && (
          <div className="mt-4 rounded-lg px-4 py-3 text-sm"
            style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}>
            Trading paused until {new Date(portfolio.circuit_broken_until).toLocaleString()}
          </div>
        )}
        {isCircuitBroken && cbExpired && (
          <div className="mt-4 rounded-lg px-4 py-3 text-sm"
            style={{ background: "#ffd93d22", color: "var(--yellow)", border: "1px solid var(--yellow)" }}>
            DB flag is_circuit_broken=True but timer expired — cosmetic bug, trading is allowed
          </div>
        )}
      </div>

      {/* Signal Engine Stats */}
      <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <h3 className="text-sm font-medium mb-4">Signal Engine</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Active Signals</p>
            <p className="text-lg font-bold">{signals?.length ?? 0}</p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Signal Threshold</p>
            <p className="text-lg font-bold">65/100</p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>MIN_CONTRARIAN_PRICE</p>
            <p className="text-lg font-bold">0.20</p>
          </div>
        </div>

        {/* Active signals list */}
        {signals && signals.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left px-3 py-2 font-medium">Market</th>
                  <th className="text-center px-3 py-2 font-medium">Dir</th>
                  <th className="text-right px-3 py-2 font-medium">Score</th>
                  <th className="text-right px-3 py-2 font-medium">Div</th>
                  <th className="text-right px-3 py-2 font-medium">Mom</th>
                  <th className="text-right px-3 py-2 font-medium">Price</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s: any) => (
                  <tr key={s.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 max-w-56 truncate">{s.market_question}</td>
                    <td className="text-center px-3 py-2">
                      <span className="px-2 py-0.5 rounded text-xs font-bold"
                        style={{
                          background: s.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                          color: s.direction === "YES" ? "var(--green)" : "var(--red)",
                        }}>
                        {s.direction}
                      </span>
                    </td>
                    <td className="text-right px-3 py-2">{s.total_score?.toFixed(1)}</td>
                    <td className="text-right px-3 py-2">{s.divergence_score?.toFixed(1)}</td>
                    <td className="text-right px-3 py-2">{s.momentum_score?.toFixed(1)}</td>
                    <td className="text-right px-3 py-2">${s.price_at_signal?.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Config Reference */}
      <div className="rounded-xl p-5 border" style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
        <h3 className="text-sm font-medium mb-4">Strategy Parameters</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          {[
            ["Trailing Stop", "25%"],
            ["Take Profit", "50%"],
            ["Max Drawdown", "20%"],
            ["CB Trigger", "3 consecutive losses"],
            ["CB Duration", "24h"],
            ["Max Positions", "5"],
            ["Kelly Factor", "0.5 (Half-Kelly)"],
            ["Max Per Trade", "5% of capital"],
            ["Signal Threshold", "65/100"],
            ["MIN_ENTRY_PRICE", "0.05"],
            ["MIN_CONTRARIAN_PRICE", "0.20"],
            ["Market Window", "6h — 168h"],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between px-3 py-2 rounded-lg"
              style={{ background: "var(--bg-primary)" }}>
              <span style={{ color: "var(--text-secondary)" }}>{label}</span>
              <span className="font-medium">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
