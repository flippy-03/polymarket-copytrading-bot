"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { href: "/analytics", label: "Analytics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { href: "/conclusions", label: "Conclusiones", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" },
  { href: "/services", label: "Services", icon: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" },
  { href: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 flex flex-col border-r"
      style={{ background: "var(--bg-secondary)", borderColor: "var(--border)" }}>
      {/* Logo */}
      <div className="p-5 border-b" style={{ borderColor: "var(--border)" }}>
        <h1 className="text-lg font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
          Polymarket Trading
        </h1>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
          Contrarian Bot
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map(({ href, label, icon }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors"
              style={{
                background: active ? "var(--bg-card)" : "transparent",
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
              }}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
              </svg>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t space-y-2 text-xs" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
        <BotStatusIndicator />
        <LlmStatusIndicator />
        <AutoRefreshIndicator />
      </div>
    </aside>
  );
}

function BotStatusIndicator() {
  const [status, setStatus] = useState<{ running: boolean; reason: string } | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const p = await fetch("/api/portfolio").then((r) => r.json());
        if (!p || p.error) { setStatus(null); return; }

        const cbActive =
          p.is_circuit_broken &&
          p.circuit_broken_until &&
          new Date(p.circuit_broken_until) > new Date();

        const currentDrawdown =
          p.initial_capital > 0
            ? (p.initial_capital - p.current_capital) / p.initial_capital
            : 0;

        if (cbActive) {
          setStatus({ running: false, reason: "Circuit Breaker" });
        } else if (currentDrawdown >= 0.20) {
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
  }, []);

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
        {status.running ? "Running" : `Paused — ${status.reason}`}
      </span>
    </div>
  );
}

function LlmStatusIndicator() {
  const [state, setState] = useState<"disabled" | "no_key" | "ready" | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const d = await fetch("/api/config").then((r) => r.json());
        if (!d.llm_enabled) {
          setState("disabled");
        } else if (!d.llm_api_key) {
          setState("no_key");
        } else {
          setState("ready");
        }
      } catch {
        setState(null);
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!state) return null;

  const colors: Record<typeof state, string> = {
    disabled: "var(--text-secondary)",
    no_key: "#f59e0b",
    ready: "var(--green)",
  };
  const labels: Record<typeof state, string> = {
    disabled: "LLM — Off",
    no_key: "LLM — No key",
    ready: "LLM — Active",
  };

  return (
    <div className="flex items-center gap-2">
      <span
        className="w-2 h-2 rounded-full"
        style={{
          background: colors[state],
          boxShadow: state === "ready" ? "0 0 6px var(--green)" : undefined,
        }}
      />
      <span style={{ color: colors[state], fontWeight: state === "ready" ? 600 : 400 }}>
        {labels[state]}
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
