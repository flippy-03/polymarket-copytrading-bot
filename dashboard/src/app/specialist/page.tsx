"use client";

import { useCallback } from "react";
import { useAutoRefresh, timeAgo, formatPnl, pnlColor } from "@/lib/hooks";
import { ctxQueryString, useStrategy } from "@/lib/strategy-context";

type UniverseSummary = {
  universe: string;
  capital_pct: number;
  max_slots: number;
  open_slots: number;
  capital_used: number;
  unrealized_pnl: number | null;
  specialists_known: number;
};

type TypeRanking = {
  market_type: string;
  n_specialists: number;
  avg_hit_rate: number;
  top_hit_rate: number;
  total_trades: number;
  priority_score: number;
  last_updated_ts: number;
};

type Specialist = {
  wallet: string;
  universe: string;
  hit_rate: number;
  specialist_score: number;
  universe_trades: number;
  universe_wins: number;
  current_streak: number;
  last_active_ts: number;
  avg_position_usd: number;
  rank_position: number | null;
};

const UNIVERSE_LABELS: Record<string, string> = {
  crypto_above_below: "Crypto Above/Below",
  crypto_price_range: "Crypto Price Range",
  sports_game_winner: "Sports Winners",
};

export default function SpecialistPage() {
  const { strategy, runId, shadowMode } = useStrategy();
  const ctx = ctxQueryString(strategy, runId, shadowMode);

  const universesFetcher = useCallback(
    () => fetch(`/api/specialist/universes?${ctx}`).then((r) => r.json()),
    [ctx],
  );
  const { data: universes } = useAutoRefresh<UniverseSummary[]>(universesFetcher);

  const typeRankingsFetcher = useCallback(
    () => fetch("/api/specialist/type-rankings").then((r) => r.json()),
    [],
  );
  const { data: typeRankings } = useAutoRefresh<TypeRanking[]>(typeRankingsFetcher, 60000);

  const specialistsFetcher = useCallback(
    () => fetch(`/api/specialist/specialists?limit=30&${ctx}`).then((r) => r.json()),
    [ctx],
  );
  const { data: specialists } = useAutoRefresh<Specialist[]>(specialistsFetcher);

  return (
    <div className="space-y-6 max-w-7xl">
      <div>
        <h2 className="text-xl font-bold">Specialist Edge</h2>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
          Event-driven specialist discovery — compound daily
        </p>
      </div>

      {/* Universe cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(universes ?? []).map((u) => (
          <div
            key={u.universe}
            className="rounded-xl border p-5 space-y-3"
            style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
          >
            <div>
              <p className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                {(u.capital_pct * 100).toFixed(0)}% allocation
              </p>
              <h3 className="text-sm font-bold mt-0.5">
                {UNIVERSE_LABELS[u.universe] ?? u.universe}
              </h3>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Slots</p>
                <p className="font-semibold">
                  {u.open_slots} / {u.max_slots}
                </p>
              </div>
              <div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Capital used</p>
                <p className="font-semibold">${u.capital_used.toFixed(0)}</p>
              </div>
              <div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Unrealized P&L</p>
                <p className="font-semibold" style={{ color: pnlColor(u.unrealized_pnl) }}>
                  {formatPnl(u.unrealized_pnl)}
                </p>
              </div>
              <div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>Specialists in DB</p>
                <p className="font-semibold">{u.specialists_known}</p>
              </div>
            </div>
          </div>
        ))}
        {(universes ?? []).length === 0 && (
          <div
            className="col-span-3 rounded-xl border p-8 text-center text-sm"
            style={{
              background: "var(--bg-card)",
              borderColor: "var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            No universe data — run --bootstrap to populate the specialist DB
          </div>
        )}
      </div>

      {/* Type rankings */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium">Market Type Rankings</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                <th className="text-left px-5 py-2 font-medium">Type</th>
                <th className="text-right px-3 py-2 font-medium">Priority</th>
                <th className="text-right px-3 py-2 font-medium">Specialists</th>
                <th className="text-right px-3 py-2 font-medium">Top HR</th>
                <th className="text-right px-3 py-2 font-medium">Avg HR</th>
                <th className="text-right px-5 py-2 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {(typeRankings ?? []).map((t) => (
                <tr key={t.market_type} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-5 py-2.5 font-mono text-xs">{t.market_type}</td>
                  <td className="text-right px-3 py-2.5">
                    <span
                      className="px-2 py-0.5 rounded text-xs font-bold"
                      style={{
                        background: t.priority_score >= 0.7
                          ? "var(--green-dim)"
                          : t.priority_score >= 0.4
                          ? "#f9731622"
                          : "var(--bg-secondary)",
                        color: t.priority_score >= 0.7
                          ? "var(--green)"
                          : t.priority_score >= 0.4
                          ? "#f97316"
                          : "var(--text-secondary)",
                      }}
                    >
                      {t.priority_score.toFixed(3)}
                    </span>
                  </td>
                  <td className="text-right px-3 py-2.5">{t.n_specialists}</td>
                  <td className="text-right px-3 py-2.5">{(t.top_hit_rate * 100).toFixed(1)}%</td>
                  <td className="text-right px-3 py-2.5">{(t.avg_hit_rate * 100).toFixed(1)}%</td>
                  <td className="text-right px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                    {t.last_updated_ts ? timeAgo(new Date(t.last_updated_ts * 1000).toISOString()) : "—"}
                  </td>
                </tr>
              ))}
              {(typeRankings ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center" style={{ color: "var(--text-secondary)" }}>
                    No type rankings yet — recomputed every 6h after bootstrap
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Specialist ranking */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
          <h3 className="text-sm font-medium">Specialist DB (top 30 by score)</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                <th className="text-left px-5 py-2 font-medium">#</th>
                <th className="text-left px-3 py-2 font-medium">Wallet</th>
                <th className="text-left px-3 py-2 font-medium">Universe</th>
                <th className="text-right px-3 py-2 font-medium">Score</th>
                <th className="text-right px-3 py-2 font-medium">Hit Rate</th>
                <th className="text-right px-3 py-2 font-medium">Trades</th>
                <th className="text-right px-3 py-2 font-medium">Streak</th>
                <th className="text-right px-5 py-2 font-medium">Last Active</th>
              </tr>
            </thead>
            <tbody>
              {(specialists ?? []).map((s, i) => (
                <tr key={`${s.wallet}-${s.universe}`} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                    {s.rank_position ?? i + 1}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">
                    {s.wallet.slice(0, 10)}…
                  </td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {UNIVERSE_LABELS[s.universe] ?? s.universe}
                  </td>
                  <td className="text-right px-3 py-2.5 font-semibold">
                    {s.specialist_score.toFixed(3)}
                  </td>
                  <td
                    className="text-right px-3 py-2.5 font-semibold"
                    style={{ color: s.hit_rate >= 0.65 ? "var(--green)" : "var(--text-primary)" }}
                  >
                    {(s.hit_rate * 100).toFixed(1)}%
                  </td>
                  <td className="text-right px-3 py-2.5">
                    {s.universe_wins}W / {s.universe_trades - s.universe_wins}L
                  </td>
                  <td className="text-right px-3 py-2.5">
                    {s.current_streak > 0 ? (
                      <span style={{ color: "var(--green)" }}>+{s.current_streak}</span>
                    ) : "—"}
                  </td>
                  <td className="text-right px-5 py-2.5" style={{ color: "var(--text-secondary)" }}>
                    {s.last_active_ts
                      ? timeAgo(new Date(s.last_active_ts * 1000).toISOString())
                      : "—"}
                  </td>
                </tr>
              ))}
              {(specialists ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="px-5 py-8 text-center" style={{ color: "var(--text-secondary)" }}>
                    No specialists in DB yet — run --bootstrap to seed the database
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
