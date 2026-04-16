"use client";

import { useCallback } from "react";
import { useAutoRefresh, timeAgo } from "@/lib/hooks";
import { useStrategy } from "@/lib/strategy-context";

type PoolRow = {
  wallet_address: string;
  status: "POOL" | "ACTIVE_TITULAR" | "QUARANTINE";
  sharpe_14d: number | null;
  rank_position: number | null;
  capital_allocated_usd: number | null;
  entered_at: string;
};

type RotationEntry = {
  wallet?: string;
  wallet_address?: string;
  sharpe_14d?: number | null;
  pnl_14d?: number | null;
};

type RotationEvent = {
  id: string;
  rotation_at: string;
  reason: string | null;
  removed_titulars: RotationEntry[] | null;
  new_titulars: RotationEntry[] | null;
  pool_snapshot: unknown;
};

type Response = {
  history: RotationEvent[];
  pool: PoolRow[];
  consecutive_losses: number;
  is_circuit_broken: boolean;
};

export default function RotationPage() {
  const { runId } = useStrategy();
  const fetcher = useCallback(() => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    const qs = params.toString();
    return fetch(`/api/rotation${qs ? `?${qs}` : ""}`).then((r) => r.json());
  }, [runId]);
  const { data, loading } = useAutoRefresh<Response>(fetcher, 60000);

  const pool = data?.pool ?? [];
  const history = data?.history ?? [];
  const consecutiveLosses = data?.consecutive_losses ?? 0;
  const isCircuitBroken = data?.is_circuit_broken ?? false;

  const titulars = pool.filter((p) => p.status === "ACTIVE_TITULAR");
  const benched = pool.filter((p) => p.status === "POOL");
  const quarantined = pool.filter((p) => p.status === "QUARANTINE");

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold">Scalper Rotation</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Weekly pool rotation ranked by 14d Sharpe (Mon 00:00 UTC)
          </p>
        </div>
        {(isCircuitBroken || consecutiveLosses > 0) && (
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{
              background: isCircuitBroken ? "var(--red-dim)" : "#ffd93d22",
              color: isCircuitBroken ? "var(--red)" : "var(--yellow)",
              border: `1px solid ${isCircuitBroken ? "var(--red)" : "var(--yellow)"}`,
            }}
          >
            {isCircuitBroken ? "⚡ CB ACTIVE" : `${consecutiveLosses}L streak`}
          </div>
        )}
      </div>

      {loading && !data && (
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading…
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <PoolSection
          title="Active Titulars"
          rows={titulars}
          accent="green"
          emptyHint="Run run_scalper_rotation.py --force to promote titulars."
        />
        <PoolSection title="Pool (benched)" rows={benched} accent="blue" />
        <PoolSection title="Quarantine" rows={quarantined} accent="red" />
      </div>

      <div>
        <h3 className="text-sm font-medium mb-3">Rotation History</h3>
        {history.length === 0 ? (
          <div
            className="rounded-xl p-6 border text-center text-sm"
            style={{
              background: "var(--bg-card)",
              borderColor: "var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            No rotations executed yet.
          </div>
        ) : (
          <div className="space-y-3">
            {history.map((h) => (
              <RotationRow key={h.id} event={h} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PoolSection({
  title,
  rows,
  accent,
  emptyHint,
}: {
  title: string;
  rows: PoolRow[];
  accent: "green" | "blue" | "red";
  emptyHint?: string;
}) {
  const bg = `var(--${accent}-dim)`;
  const fg = `var(--${accent})`;
  return (
    <div
      className="rounded-xl p-5 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold">{title}</h3>
        <span
          className="px-2 py-0.5 rounded text-[10px] font-bold"
          style={{ background: bg, color: fg }}
        >
          {rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <div
          className="text-[11px]"
          style={{ color: "var(--text-secondary)" }}
        >
          {emptyHint ?? "Empty"}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div
              key={r.wallet_address}
              className="flex items-center justify-between text-[11px]"
            >
              <span className="font-mono">
                #{r.rank_position ?? "?"}{" "}
                <a
                  href={`https://polymarket.com/profile/${r.wallet_address}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--blue)" }}
                >
                  {r.wallet_address.slice(0, 6)}…{r.wallet_address.slice(-4)}
                </a>
              </span>
              <span style={{ color: "var(--text-secondary)" }}>
                Sh {r.sharpe_14d?.toFixed(2) ?? "—"}
                {r.capital_allocated_usd != null &&
                  r.capital_allocated_usd > 0 &&
                  ` · $${r.capital_allocated_usd.toFixed(0)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RotationRow({ event }: { event: RotationEvent }) {
  return (
    <div
      className="rounded-xl p-4 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between mb-2 text-xs">
        <div>
          <span className="font-bold">
            {new Date(event.rotation_at).toLocaleString()}
          </span>
          {event.reason && (
            <span
              className="ml-3 px-2 py-0.5 rounded text-[10px] font-bold"
              style={{ background: "var(--blue-dim)", color: "var(--blue)" }}
            >
              {event.reason}
            </span>
          )}
        </div>
        <span style={{ color: "var(--text-secondary)" }}>
          {timeAgo(event.rotation_at)} ago
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px]">
        <div>
          <div
            className="font-medium mb-1"
            style={{ color: "var(--red)" }}
          >
            Removed
          </div>
          {(event.removed_titulars ?? []).length === 0 ? (
            <div style={{ color: "var(--text-secondary)" }}>—</div>
          ) : (
            (event.removed_titulars ?? []).map((w, i) => (
              <RotationEntryRow key={i} entry={w} />
            ))
          )}
        </div>
        <div>
          <div
            className="font-medium mb-1"
            style={{ color: "var(--green)" }}
          >
            New
          </div>
          {(event.new_titulars ?? []).length === 0 ? (
            <div style={{ color: "var(--text-secondary)" }}>—</div>
          ) : (
            (event.new_titulars ?? []).map((w, i) => (
              <RotationEntryRow key={i} entry={w} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function RotationEntryRow({ entry }: { entry: RotationEntry }) {
  const addr = entry.wallet ?? entry.wallet_address ?? "";
  return (
    <div className="flex items-center justify-between font-mono">
      <span>
        {addr ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : "—"}
      </span>
      <span style={{ color: "var(--text-secondary)" }}>
        Sh {entry.sharpe_14d?.toFixed(2) ?? "—"}
        {entry.pnl_14d != null && ` · $${entry.pnl_14d.toFixed(0)}`}
      </span>
    </div>
  );
}
