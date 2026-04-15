"use client";

import { useCallback } from "react";
import { useAutoRefresh } from "@/lib/hooks";
import { useStrategy } from "@/lib/strategy-context";
import type { PortfolioState } from "@/lib/types";

const SERVICES_BY_STRATEGY: Record<string, { name: string; desc: string }[]> = {
  BASKET: [
    { name: "run_basket_strategy.py --run", desc: "Basket monitor + executor loop (polling 60s)" },
    { name: "run_basket_strategy.py --build-only", desc: "Daily/weekly basket rebuild (crypto/economics/politics)" },
  ],
  SCALPER: [
    { name: "run_scalper_strategy.py --run", desc: "Scalper copy monitor (titulars polling 30s)" },
    { name: "run_scalper_strategy.py --build-pool", desc: "Rebuild the 8-12 wallet scalper pool" },
    { name: "run_scalper_rotation.py", desc: "Weekly rotation by Sharpe 14d (Mon 00:00 UTC)" },
  ],
};

export default function ServicesPage() {
  const { strategy } = useStrategy();

  const portfolioFetcher = useCallback(
    () => fetch(`/api/portfolio?strategy=${strategy}`).then((r) => r.json()),
    [strategy],
  );
  const { data: portfolio } = useAutoRefresh<PortfolioState>(portfolioFetcher);

  const services = SERVICES_BY_STRATEGY[strategy] ?? [];

  const isCircuitBroken = portfolio?.is_circuit_broken ?? false;
  const cbExpired = portfolio?.circuit_broken_until
    ? new Date(portfolio.circuit_broken_until) < new Date()
    : true;
  const cbActive = isCircuitBroken && !cbExpired;

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-xl font-bold">{strategy} Services</h2>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          Daemons and jobs backing this strategy
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {services.map((svc) => (
          <div
            key={svc.name}
            className="rounded-xl p-5 border"
            style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
          >
            <div className="flex items-center gap-3 mb-2">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--blue)" }} />
              <h3 className="text-sm font-mono">{svc.name}</h3>
            </div>
            <p className="text-xs ml-5" style={{ color: "var(--text-secondary)" }}>
              {svc.desc}
            </p>
          </div>
        ))}
      </div>

      <div
        className="rounded-xl p-5 border"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <h3 className="text-sm font-medium mb-4">Circuit Breaker</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Status</p>
            <p
              className="text-lg font-bold"
              style={{ color: cbActive ? "var(--red)" : "var(--green)" }}
            >
              {cbActive ? "ACTIVE" : "OK"}
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Consecutive Losses</p>
            <p
              className="text-lg font-bold"
              style={{
                color: (portfolio?.consecutive_losses ?? 0) >= 2 ? "var(--red)" : "var(--text-primary)",
              }}
            >
              {portfolio?.consecutive_losses ?? 0} / 3
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Max Drawdown</p>
            <p className="text-lg font-bold">
              {((Number(portfolio?.max_drawdown ?? 0)) * 100).toFixed(1)}% / 30%
            </p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Open Slots</p>
            <p className="text-lg font-bold">
              {portfolio?.open_positions ?? 0} / {portfolio?.max_open_positions ?? 0}
            </p>
          </div>
        </div>
        {cbActive && portfolio?.circuit_broken_until && (
          <div
            className="mt-4 rounded-lg px-4 py-3 text-sm"
            style={{ background: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}
          >
            Trading paused until {new Date(portfolio.circuit_broken_until).toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}
