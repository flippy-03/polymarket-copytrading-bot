"use client";

import { useCallback } from "react";
import { useAutoRefresh, timeAgo } from "@/lib/hooks";

type BasketMember = {
  wallet_address: string;
  rank_position: number | null;
  rank_score: number | null;
  entered_at: string;
};

type BasketSignal = {
  id: string;
  market_polymarket_id: string;
  market_question: string | null;
  direction: "YES" | "NO";
  consensus_pct: number | null;
  wallets_agreeing: number | null;
  wallets_total: number | null;
  status: string;
  price_at_signal: number | null;
  created_at: string;
};

type Basket = {
  id: string;
  category: string;
  status: string;
  consensus_threshold: number;
  time_window_hours: number;
  max_capital_pct: number;
  updated_at: string;
  members: BasketMember[];
  member_count: number;
  signals: BasketSignal[];
  pending_signals: number;
};

export default function BasketsPage() {
  const fetcher = useCallback(
    () => fetch("/api/baskets").then((r) => r.json()),
    [],
  );
  const { data, loading } = useAutoRefresh<Basket[]>(fetcher, 30000);

  return (
    <div className="space-y-6 max-w-7xl">
      <div>
        <h2 className="text-xl font-bold">Baskets</h2>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          Thematic wallet groupings powering the Basket Consensus strategy
        </p>
      </div>

      {loading && !data && (
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading…
        </div>
      )}

      {!loading && (!data || data.length === 0) && (
        <div
          className="rounded-xl p-8 border text-center text-sm"
          style={{
            background: "var(--bg-card)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          No active baskets. Run <code>run_basket_strategy.py --build-only</code>.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {(data ?? []).map((b) => (
          <BasketCard key={b.id} basket={b} />
        ))}
      </div>

      {data && data.some((b) => b.signals.length > 0) && (
        <div>
          <h3 className="text-sm font-medium mb-3">Recent Signals</h3>
          <div
            className="rounded-xl border overflow-x-auto"
            style={{
              background: "var(--bg-card)",
              borderColor: "var(--border)",
            }}
          >
            <table className="w-full text-xs">
              <thead>
                <tr
                  className="text-left"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <th className="p-3">Basket</th>
                  <th className="p-3">Market</th>
                  <th className="p-3">Direction</th>
                  <th className="p-3">Consensus</th>
                  <th className="p-3">Price</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Age</th>
                </tr>
              </thead>
              <tbody>
                {data
                  .flatMap((b) =>
                    b.signals.map((s) => ({ basket: b.category, ...s })),
                  )
                  .slice(0, 50)
                  .map((s) => (
                    <tr
                      key={s.id}
                      className="border-t"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <td className="p-3">{s.basket}</td>
                      <td className="p-3 max-w-xs truncate">
                        {s.market_question ?? s.market_polymarket_id}
                      </td>
                      <td className="p-3">
                        <DirBadge dir={s.direction} />
                      </td>
                      <td className="p-3">
                        {s.consensus_pct != null
                          ? `${(s.consensus_pct * 100).toFixed(0)}%`
                          : "—"}{" "}
                        ({s.wallets_agreeing}/{s.wallets_total})
                      </td>
                      <td className="p-3">
                        {s.price_at_signal?.toFixed(3) ?? "—"}
                      </td>
                      <td className="p-3">
                        <StatusBadge status={s.status} />
                      </td>
                      <td
                        className="p-3"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {timeAgo(s.created_at)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function BasketCard({ basket }: { basket: Basket }) {
  return (
    <div
      className="rounded-xl p-5 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold">{basket.category}</h3>
        <span
          className="px-2 py-0.5 rounded text-[10px] font-bold"
          style={{ background: "var(--blue-dim)", color: "var(--blue)" }}
        >
          {basket.member_count} wallets
        </span>
      </div>
      <div
        className="text-[11px] mb-3"
        style={{ color: "var(--text-secondary)" }}
      >
        Consensus ≥{(basket.consensus_threshold * 100).toFixed(0)}% in{" "}
        {basket.time_window_hours}h · max{" "}
        {(basket.max_capital_pct * 100).toFixed(0)}% capital
      </div>
      {basket.pending_signals > 0 && (
        <div
          className="text-[11px] mb-3 px-2 py-1 rounded"
          style={{ background: "var(--green-dim)", color: "var(--green)" }}
        >
          {basket.pending_signals} pending signal(s)
        </div>
      )}
      <div className="space-y-1">
        {basket.members.slice(0, 10).map((m) => (
          <div
            key={m.wallet_address}
            className="flex items-center justify-between text-[11px]"
          >
            <span className="font-mono">
              #{m.rank_position ?? "?"}{" "}
              <a
                href={`https://polymarket.com/profile/${m.wallet_address}`}
                target="_blank"
                rel="noreferrer"
                style={{ color: "var(--blue)" }}
              >
                {m.wallet_address.slice(0, 6)}…{m.wallet_address.slice(-4)}
              </a>
            </span>
            <span style={{ color: "var(--text-secondary)" }}>
              {m.rank_score != null ? m.rank_score.toFixed(2) : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DirBadge({ dir }: { dir: "YES" | "NO" }) {
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] font-bold"
      style={{
        background: dir === "YES" ? "var(--green-dim)" : "var(--red-dim)",
        color: dir === "YES" ? "var(--green)" : "var(--red)",
      }}
    >
      {dir}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    PENDING: { bg: "var(--blue-dim)", fg: "var(--blue)" },
    EXECUTED: { bg: "var(--green-dim)", fg: "var(--green)" },
    EXPIRED: { bg: "var(--bg-card)", fg: "var(--text-secondary)" },
    REJECTED: { bg: "var(--red-dim)", fg: "var(--red)" },
  };
  const c = map[status] ?? {
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
