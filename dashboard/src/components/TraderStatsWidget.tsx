"use client";

import { useEffect, useState } from "react";

/**
 * Compact trader stats card — our own replacement for the polymarketscan.org
 * embed iframe. Same visual grammar (dark card, KPI grid) but sourced from
 * our internal wallet_profiles + wallet_metrics tables and rendered as native
 * React (no iframe, no CORS, no external downtime).
 *
 * Two layouts:
 *  - Default: 400×400, full stats block (Total PnL, ROI, Win Rate, Trades,
 *    Volume, W/L, Markets, Best/Worst Trade).
 *  - Compact: inline in cards/popovers — hides Best/Worst.
 */

type Props = {
  wallet: string;
  width?: number;
  height?: number;
  compact?: boolean;
  // When true the component defers the fetch by 300 ms so a fast scroll over a
  // list doesn't fire dozens of requests.
  hoverMode?: boolean;
};

type StatsResponse = {
  wallet: string;
  handle?: string | null;
  total_pnl?: number | null;
  roi_pct?: number | null;
  win_rate?: number | null;
  total_trades?: number | null;
  total_volume_usd?: number | null;
  wins?: number | null;
  losses?: number | null;
  unique_markets?: number | null;
  best_trade?: number | null;
  worst_trade?: number | null;
};

function fmtUsd(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(v >= 100 ? 0 : 2)}`;
}

function fmtPct(v: number | null | undefined, decimals = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v >= 0 ? "" : ""}${(v * 100).toFixed(decimals)}%`;
}

function fmtSignedUsd(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "" : "";
  return `${sign}${fmtUsd(v)}`;
}

function pnlColor(v: number | null | undefined): string {
  if (v == null) return "var(--text-secondary)";
  if (v > 0) return "var(--green)";
  if (v < 0) return "var(--red)";
  return "var(--text-secondary)";
}

export function TraderStatsWidget({
  wallet,
  width = 400,
  height = 400,
  compact = false,
  hoverMode = false,
}: Props) {
  const [data, setData] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    const start = () => {
      fetch(`/api/wallets/${wallet}/stats`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d: StatsResponse) => {
          if (!cancelled) setData(d);
        })
        .catch(() => {
          if (!cancelled) setError(true);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    const timer = hoverMode ? setTimeout(start, 300) : (start(), null);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [wallet, hoverMode]);

  const shortWallet = `${wallet.slice(0, 6)}…${wallet.slice(-4)}`;
  const handle = data?.handle || shortWallet;

  return (
    <div
      style={{
        width,
        height,
        borderRadius: 14,
        background: "linear-gradient(180deg, #0e141c 0%, #0a0e15 100%)",
        border: "1px solid #1f2937",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        color: "var(--text-primary)",
        boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: "50%",
            background: `linear-gradient(135deg, #2b8fd9 0%, #1e6faf 100%)`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 13,
            color: "#fff",
            textTransform: "uppercase",
          }}
        >
          {wallet.slice(2, 3)}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{handle}</div>
          <div style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "monospace" }}>
            {shortWallet}
          </div>
        </div>
      </div>

      {/* Total PnL block */}
      <div
        style={{
          background: "#0c1220",
          borderRadius: 10,
          padding: "14px 12px",
          textAlign: "center",
          border: "1px solid #14202e",
        }}
      >
        <div style={{ fontSize: 10, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>
          Total PnL
        </div>
        {loading ? (
          <Skeleton height={22} width={90} />
        ) : error ? (
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Stats not available
          </div>
        ) : (
          <>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                marginTop: 4,
                color: pnlColor(data?.total_pnl),
              }}
            >
              {fmtSignedUsd(data?.total_pnl)}
            </div>
            {data?.roi_pct != null && (
              <div
                style={{
                  fontSize: 11,
                  marginTop: 2,
                  color: pnlColor(data.roi_pct),
                }}
              >
                {data.roi_pct >= 0 ? "+" : ""}
                {(data.roi_pct * 100).toFixed(1)}% ROI
              </div>
            )}
          </>
        )}
      </div>

      {/* KPI pills grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <Pill label="Win Rate" value={fmtPct(data?.win_rate)} valueColor={data?.win_rate != null && data.win_rate >= 0.55 ? "var(--green)" : undefined} loading={loading} />
        <Pill label="Trades" value={data?.total_trades != null ? String(data.total_trades) : "—"} loading={loading} />
        <Pill label="Volume" value={fmtUsd(data?.total_volume_usd)} loading={loading} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Pill
          label="W/L"
          value={
            data?.wins != null && data?.losses != null
              ? `${data.wins} / ${data.losses}`
              : "—"
          }
          loading={loading}
        />
        <Pill label="Markets" value={data?.unique_markets != null ? String(data.unique_markets) : "—"} loading={loading} />
      </div>

      {/* Best / Worst (skip on compact) */}
      {!compact && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <Pill
            label="Best Trade"
            value={fmtSignedUsd(data?.best_trade)}
            valueColor={data?.best_trade != null && data.best_trade > 0 ? "var(--green)" : undefined}
            loading={loading}
          />
          <Pill
            label="Worst Trade"
            value={fmtSignedUsd(data?.worst_trade)}
            valueColor={data?.worst_trade != null && data.worst_trade < 0 ? "var(--red)" : undefined}
            loading={loading}
          />
        </div>
      )}

      {/* Footer attribution */}
      <div
        style={{
          marginTop: "auto",
          fontSize: 9,
          color: "var(--text-secondary)",
          textAlign: "right",
          letterSpacing: 0.5,
        }}
      >
        Powered by our bot · live from wallet_profiles
      </div>
    </div>
  );
}

function Pill({
  label,
  value,
  valueColor,
  loading,
}: {
  label: string;
  value: string;
  valueColor?: string;
  loading?: boolean;
}) {
  return (
    <div
      style={{
        background: "#10172000",
        border: "1px solid #1f2937",
        borderRadius: 8,
        padding: "8px 10px",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: 0.5 }}>{label}</div>
      {loading ? (
        <div style={{ marginTop: 4 }}>
          <Skeleton height={14} width={40} />
        </div>
      ) : (
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            marginTop: 2,
            color: valueColor || "var(--text-primary)",
          }}
        >
          {value}
        </div>
      )}
    </div>
  );
}

function Skeleton({ height, width }: { height: number; width: number }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 4,
        background: "linear-gradient(90deg, #1a2432 0%, #253040 50%, #1a2432 100%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 1.2s infinite linear",
        display: "inline-block",
      }}
    >
      <style>{`@keyframes shimmer { 0% {background-position: 200% 0;} 100% {background-position: -200% 0;} }`}</style>
    </div>
  );
}
