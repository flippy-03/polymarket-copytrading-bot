"use client";

import { useCallback, useMemo, useState } from "react";
import { useAutoRefresh } from "@/lib/hooks";
import { ctxQueryString, useStrategy } from "@/lib/strategy-context";

type WalletRow = {
  wallet_address: string;
  snapshot_at?: string;
  win_rate?: number | null;
  total_trades?: number | null;
  pnl_30d?: number | null;
  pnl_7d?: number | null;
  profit_factor?: number | null;
  avg_holding_days?: number | null;
  trades_per_month?: number | null;
  sharpe_14d?: number | null;
  bot_score?: number | null;
  tier1_pass?: boolean | null;
  tier2_score?: number | null;
  scalper?: {
    status?: string;
    sharpe_14d?: number | null;
    rank_position?: number | null;
    capital_allocated_usd?: number | null;
  };
  specialist?: {
    wallet?: string;
    universe?: string | null;
    rank_position?: number | null;
    specialist_score?: number | null;
  };
};

type SortKey = "sharpe" | "pnl30" | "win" | "trades";

export default function WalletsPage() {
  const { strategy, runId, shadowMode } = useStrategy();
  const source = strategy === "SCALPER" ? "scalper" : "specialist";
  const [sortKey, setSortKey] = useState<SortKey>("sharpe");
  const ctx = ctxQueryString(strategy, runId, shadowMode);

  const fetcher = useCallback(
    () => fetch(`/api/wallets?${ctx}&source=${source}`).then((r) => r.json()),
    [ctx, source],
  );
  const { data, loading } = useAutoRefresh<WalletRow[]>(fetcher, 60000);

  const rows = useMemo(() => {
    const list = Array.isArray(data) ? [...data] : [];
    const key: Record<SortKey, (r: WalletRow) => number> = {
      sharpe: (r) => r.scalper?.sharpe_14d ?? r.sharpe_14d ?? -999,
      pnl30: (r) => r.pnl_30d ?? -1e9,
      win: (r) => r.win_rate ?? -1,
      trades: (r) => r.total_trades ?? -1,
    };
    return list.sort((a, b) => key[sortKey](b) - key[sortKey](a));
  }, [data, sortKey]);

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">
            {strategy === "SCALPER" ? "Scalper Pool" : "Specialist Rankings"}
          </h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {strategy === "SCALPER"
              ? "8-12 traders ranked by 14d Sharpe, rotated weekly"
              : "Top specialists across universes: crypto, sports"}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span style={{ color: "var(--text-secondary)" }}>Sort:</span>
          {(["sharpe", "pnl30", "win", "trades"] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortKey(k)}
              className="px-2 py-1 rounded"
              style={{
                background:
                  sortKey === k ? "var(--blue-dim)" : "var(--bg-card)",
                color: sortKey === k ? "var(--blue)" : "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              {k === "sharpe"
                ? "Sharpe"
                : k === "pnl30"
                  ? "PnL 30d"
                  : k === "win"
                    ? "Win %"
                    : "Trades"}
            </button>
          ))}
        </div>
      </div>

      {loading && !data && (
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading…
        </div>
      )}

      {!loading && rows.length === 0 && (
        <div
          className="rounded-xl p-8 border text-center text-sm"
          style={{
            background: "var(--bg-card)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          No wallets tracked yet. Run{" "}
          <code>
            {strategy === "SCALPER"
              ? "run_scalper_strategy.py --build-pool"
              : "run_specialist_strategy.py --bootstrap"}
          </code>
          .
        </div>
      )}

      {rows.length > 0 && (
        <div
          className="rounded-xl border overflow-x-auto"
          style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
        >
          <table className="w-full text-xs">
            <thead>
              <tr
                className="text-left"
                style={{ color: "var(--text-secondary)" }}
              >
                <th className="p-3">Wallet</th>
                {strategy === "SCALPER" ? (
                  <>
                    <th className="p-3">Status</th>
                    <th className="p-3">Rank</th>
                    <th className="p-3">Capital</th>
                  </>
                ) : (
                  <>
                    <th className="p-3">Universe</th>
                    <th className="p-3">Rank</th>
                    <th className="p-3">Score</th>
                  </>
                )}
                <th className="p-3">Sharpe 14d</th>
                <th className="p-3">Win %</th>
                <th className="p-3">Trades</th>
                <th className="p-3">PnL 30d</th>
                <th className="p-3">PnL 7d</th>
                <th className="p-3">Avg Hold</th>
                <th className="p-3">Bot</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.wallet_address}
                  className="border-t"
                  style={{ borderColor: "var(--border)" }}
                >
                  <td className="p-3 font-mono">
                    <a
                      href={`https://polymarket.com/profile/${r.wallet_address}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: "var(--blue)" }}
                    >
                      {r.wallet_address.slice(0, 6)}…
                      {r.wallet_address.slice(-4)}
                    </a>
                  </td>
                  {strategy === "SCALPER" ? (
                    <>
                      <td className="p-3">
                        <StatusBadge status={r.scalper?.status} />
                      </td>
                      <td className="p-3">{r.scalper?.rank_position ?? "—"}</td>
                      <td className="p-3">
                        {r.scalper?.capital_allocated_usd != null
                          ? `$${r.scalper.capital_allocated_usd.toFixed(0)}`
                          : "—"}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="p-3">
                        {r.specialist?.universe ?? "—"}
                      </td>
                      <td className="p-3">{r.specialist?.rank_position ?? "—"}</td>
                      <td className="p-3">
                        {r.specialist?.specialist_score != null
                          ? r.specialist.specialist_score.toFixed(3)
                          : "—"}
                      </td>
                    </>
                  )}
                  <td className="p-3">
                    {(r.scalper?.sharpe_14d ?? r.sharpe_14d)?.toFixed(2) ?? "—"}
                  </td>
                  <td className="p-3">
                    {r.win_rate != null
                      ? `${(r.win_rate * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className="p-3">{r.total_trades ?? "—"}</td>
                  <td
                    className="p-3"
                    style={{
                      color:
                        (r.pnl_30d ?? 0) >= 0 ? "var(--green)" : "var(--red)",
                    }}
                  >
                    {r.pnl_30d != null ? `$${r.pnl_30d.toFixed(0)}` : "—"}
                  </td>
                  <td
                    className="p-3"
                    style={{
                      color:
                        (r.pnl_7d ?? 0) >= 0 ? "var(--green)" : "var(--red)",
                    }}
                  >
                    {r.pnl_7d != null ? `$${r.pnl_7d.toFixed(0)}` : "—"}
                  </td>
                  <td className="p-3">
                    {r.avg_holding_days != null
                      ? `${r.avg_holding_days.toFixed(1)}d`
                      : "—"}
                  </td>
                  <td className="p-3">
                    {r.bot_score != null ? r.bot_score.toFixed(2) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return <span>—</span>;
  const colors: Record<string, { bg: string; fg: string }> = {
    ACTIVE_TITULAR: { bg: "var(--green-dim)", fg: "var(--green)" },
    POOL: { bg: "var(--blue-dim)", fg: "var(--blue)" },
    QUARANTINE: { bg: "var(--red-dim)", fg: "var(--red)" },
  };
  const c = colors[status] ?? {
    bg: "var(--bg-card)",
    fg: "var(--text-secondary)",
  };
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] font-bold"
      style={{ background: c.bg, color: c.fg }}
    >
      {status}
    </span>
  );
}
