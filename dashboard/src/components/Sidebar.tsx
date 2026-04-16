"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ShadowMode, useStrategy } from "@/lib/strategy-context";

const NAV = [
  { href: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { href: "/analytics", label: "Analytics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { href: "/wallets", label: "Wallets", icon: "M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-2M17 9H9a2 2 0 00-2 2v2a2 2 0 002 2h8a2 2 0 002-2v-2a2 2 0 00-2-2z" },
  { href: "/specialist", label: "Specialist Edge", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" },
  { href: "/rotation", label: "Scalper Pool", icon: "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" },
  { href: "/shadow", label: "Shadow", icon: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.92 0 3.71-.54 5.23-1.47A10 10 0 0112 2zm0 18a8 8 0 110-16 8 8 0 010 16z" },
  { href: "/conclusions", label: "Conclusions", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" },
  { href: "/services", label: "Services", icon: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" },
  { href: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
];

type Run = {
  id: string;
  strategy: string;
  version: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  notes: string | null;
  parent_run_id: string | null;
};

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 h-screen w-56 flex flex-col border-r"
      style={{ background: "var(--bg-secondary)", borderColor: "var(--border)" }}
    >
      {/* Logo + strategy/run/shadow controls */}
      <div className="p-5 border-b space-y-3" style={{ borderColor: "var(--border)" }}>
        <div>
          <h1 className="text-lg font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Polymarket Copytrading
          </h1>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
            Dual strategy — paper mode
          </p>
        </div>
        <StrategySwitcher />
        <RunSelector />
        <ShadowModeToggle />
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map(({ href, label, icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors"
              style={{
                background: active ? "var(--bg-card)" : "transparent",
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
              }}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
              </svg>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div
        className="p-4 border-t space-y-2 text-xs"
        style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
      >
        <BotStatusIndicator />
        <AutoRefreshIndicator />
      </div>
    </aside>
  );
}

function StrategySwitcher() {
  const { strategy, setStrategy } = useStrategy();
  const options: { value: "SPECIALIST" | "SCALPER"; label: string }[] = [
    { value: "SPECIALIST", label: "Specialist" },
    { value: "SCALPER", label: "Scalper" },
  ];
  return (
    <div
      className="flex rounded-md p-0.5 text-xs font-medium"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {options.map((o) => {
        const active = strategy === o.value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => setStrategy(o.value)}
            className="flex-1 px-2 py-1.5 rounded transition-colors"
            style={{
              background: active ? "var(--bg-secondary)" : "transparent",
              color: active ? "var(--text-primary)" : "var(--text-secondary)",
              fontWeight: active ? 700 : 500,
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function RunSelector() {
  const { strategy, runId, setRunId } = useStrategy();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`/api/runs?strategy=${strategy}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        setRuns(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (!cancelled) setRuns([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [strategy]);

  const activeRun = runs.find((r) => r.status === "ACTIVE");
  // null value → follow ACTIVE automatically
  const selectValue = runId ?? "__active__";

  return (
    <div className="space-y-1">
      <label
        className="block text-[10px] uppercase tracking-wider"
        style={{ color: "var(--text-secondary)" }}
      >
        Run
      </label>
      <select
        value={selectValue}
        disabled={loading || runs.length === 0}
        onChange={(e) => {
          const v = e.target.value;
          setRunId(v === "__active__" ? null : v);
        }}
        className="w-full text-xs px-2 py-1.5 rounded"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          color: "var(--text-primary)",
        }}
      >
        <option value="__active__">
          {activeRun ? `Active — ${activeRun.version}` : "Active (no runs)"}
        </option>
        {runs
          .filter((r) => r.status !== "ACTIVE")
          .map((r) => (
            <option key={r.id} value={r.id}>
              {r.version} · {r.status.toLowerCase()}
            </option>
          ))}
      </select>
    </div>
  );
}

function ShadowModeToggle() {
  const { shadowMode, setShadowMode } = useStrategy();
  const options: { value: ShadowMode; label: string }[] = [
    { value: "REAL", label: "Real" },
    { value: "SHADOW", label: "Shadow" },
    { value: "BOTH", label: "Both" },
  ];
  return (
    <div className="space-y-1">
      <label
        className="block text-[10px] uppercase tracking-wider"
        style={{ color: "var(--text-secondary)" }}
      >
        View
      </label>
      <div
        className="flex rounded-md p-0.5 text-[11px] font-medium"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {options.map((o) => {
          const active = shadowMode === o.value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => setShadowMode(o.value)}
              className="flex-1 px-1.5 py-1 rounded transition-colors"
              style={{
                background: active ? "var(--bg-secondary)" : "transparent",
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
                fontWeight: active ? 700 : 500,
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function BotStatusIndicator() {
  const { strategy, runId, shadowMode } = useStrategy();
  const [status, setStatus] = useState<{ running: boolean; reason: string } | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const params = new URLSearchParams({ strategy });
        if (runId) params.set("run_id", runId);
        // Bot health is always about the REAL portfolio regardless of view toggle.
        params.set("shadow", "REAL");
        const p = await fetch(`/api/portfolio?${params.toString()}`).then((r) => r.json());
        if (!p || p.error) {
          setStatus(null);
          return;
        }

        // Mirror risk_manager_ct.is_circuit_broken() + page.tsx logic:
        // - requires_manual_review pins the CB on regardless of the timer
        // - otherwise the timer must be in the future
        const cbActive =
          p.is_circuit_broken &&
          (p.requires_manual_review ||
            (p.circuit_broken_until && new Date(p.circuit_broken_until) > new Date()));

        // ATH-based drawdown (matches risk_manager_ct.current_drawdown()).
        const current = Number(p.current_capital ?? 0);
        const peak = Number(p.peak_capital ?? p.initial_capital ?? 0);
        const currentDrawdown = peak > 0 ? Math.max(0, (peak - current) / peak) : 0;

        if (cbActive) {
          const reason = p.requires_manual_review && !p.circuit_broken_until
            ? "Manual stop"
            : "CB cooldown";
          setStatus({ running: false, reason });
        } else if (currentDrawdown >= 0.30) {
          setStatus({ running: false, reason: `DD ${(currentDrawdown * 100).toFixed(1)}%` });
        } else {
          setStatus({ running: true, reason: "ok" });
        }
      } catch {
        setStatus(null);
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
    // shadowMode intentionally excluded — indicator always reads real portfolio
  }, [strategy, runId]);

  if (!status) return null;

  return (
    <div className="flex items-center gap-2">
      <span
        className="w-2 h-2 rounded-full"
        style={{
          background: status.running ? "var(--green)" : "var(--red)",
          boxShadow: status.running ? "0 0 6px var(--green)" : "0 0 6px var(--red)",
        }}
      />
      <span style={{ color: status.running ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
        {status.running
          ? `${strategy} — running${shadowMode !== "REAL" ? ` · ${shadowMode.toLowerCase()} view` : ""}`
          : `${strategy} — paused (${status.reason})`}
      </span>
    </div>
  );
}

function AutoRefreshIndicator() {
  return (
    <div className="flex items-center gap-2">
      <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "var(--blue)" }} />
      <span>Live — 30s refresh</span>
    </div>
  );
}
