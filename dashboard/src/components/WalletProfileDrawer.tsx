"use client";

import { useEffect, useState } from "react";
import {
  formatKpi,
  getArchetype,
  getRarity,
  RARITY_STYLE,
  TRAIT_STYLE,
} from "@/lib/archetypes";
import { TraderStatsWidget } from "./TraderStatsWidget";

type FullResponse = {
  wallet: string;
  profile: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  scalper: Record<string, unknown> | null;
  specialist_rows: Record<string, unknown>[];
};

type RankingsResponse = {
  wallet: string;
  universe_size: number;
  has_data: boolean;
  volume_percentile: number | null;
  pnl_percentile: number | null;
  pnl_pct_percentile: number | null;
  account_age_percentile: number | null;
};

type Props = {
  wallet: string | null;
  onClose: () => void;
};

/**
 * Centered modal with the full enriched profile for one wallet, styled after
 * the polymarketscan.org trader page. Opens on wallet card click; closes on
 * backdrop click or Escape.
 */
export function WalletProfileDrawer({ wallet, onClose }: Props) {
  const [data, setData] = useState<FullResponse | null>(null);
  const [rankings, setRankings] = useState<RankingsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // Main profile fetch
  useEffect(() => {
    if (!wallet) {
      setData(null);
      setRankings(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/wallets/${wallet}`)
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Rankings in parallel
    fetch(`/api/wallets/${wallet}/rankings`)
      .then((r) => r.json())
      .then((d: RankingsResponse) => {
        if (!cancelled) setRankings(d);
      })
      .catch(() => {
        if (!cancelled) setRankings(null);
      });

    return () => {
      cancelled = true;
    };
  }, [wallet]);

  // Close on Escape
  useEffect(() => {
    if (!wallet) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wallet, onClose]);

  if (!wallet) return null;

  const profile = data?.profile || null;
  const metrics = data?.metrics || null;
  const archetypeId = (profile?.primary_archetype as string) || "UNKNOWN";
  const archetype = getArchetype(archetypeId);
  const rarity = getRarity(profile?.rarity_tier as string);
  const rarityStyle = RARITY_STYLE[rarity];
  const strategies: string[] = Array.isArray(profile?.strategies_active)
    ? (profile!.strategies_active as string[])
    : [];
  const traits: string[] = Array.isArray(profile?.archetype_traits)
    ? (profile!.archetype_traits as string[])
    : [];

  return (
    <>
      {/* Overlay with backdrop blur */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.55)",
          backdropFilter: "blur(6px)",
          WebkitBackdropFilter: "blur(6px)",
          zIndex: 40,
          animation: "profileFadeIn 160ms ease-out",
        }}
      />
      {/* Centered modal */}
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "min(1100px, 94vw)",
          maxHeight: "92vh",
          background: "var(--bg-primary)",
          borderRadius: 16,
          boxShadow: `0 24px 48px rgba(0,0,0,0.55), ${rarityStyle.glow}`,
          zIndex: 50,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          animation: "profileScaleIn 180ms ease-out",
        }}
      >
        <style>{`
          @keyframes profileFadeIn { from { opacity: 0; } to { opacity: 1; } }
          @keyframes profileScaleIn {
            from { opacity: 0; transform: translate(-50%, -50%) scale(0.96); }
            to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
          }
        `}</style>

        {/* ── Header ───────────────────────────────────────── */}
        <div
          style={{
            padding: "18px 22px",
            borderBottom: "1px solid var(--border)",
            background: `linear-gradient(180deg, ${archetype.color}15 0%, transparent 100%)`,
            display: "flex",
            gap: 14,
            alignItems: "flex-start",
          }}
        >
          {/* Avatar */}
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: "50%",
              background: `linear-gradient(135deg, ${archetype.color} 0%, ${archetype.color}99 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 24,
              color: "#fff",
              flexShrink: 0,
              boxShadow: `0 4px 12px ${archetype.color}66`,
            }}
          >
            {archetype.icon}
          </div>

          {/* Main header info */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>
                {wallet.slice(0, 6)}…{wallet.slice(-4)}
              </div>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "2px 6px",
                  borderRadius: 4,
                  background: "var(--bg-card)",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border)",
                  letterSpacing: 0.5,
                }}
              >
                PROXY
              </span>
              <code
                style={{
                  fontSize: 11,
                  color: "var(--text-secondary)",
                  fontFamily: "monospace",
                }}
              >
                {wallet}
              </code>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  navigator.clipboard?.writeText(wallet);
                }}
                style={{
                  fontSize: 10,
                  background: "transparent",
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                  borderRadius: 4,
                  padding: "2px 6px",
                  cursor: "pointer",
                }}
                title="Copy address"
              >
                ⧉
              </button>
            </div>

            {/* Archetype + strategies */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginTop: 8,
                flexWrap: "wrap",
              }}
            >
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: archetype.color,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                {archetype.label}
                <RarityGem color={rarityStyle.color} label={rarityStyle.label} />
              </div>
              <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                {rarityStyle.stars} {rarityStyle.label}
              </span>
              {strategies.map((s) => (
                <span
                  key={s}
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: 4,
                    background: s === "SPECIALIST" ? "var(--blue-dim)" : "var(--green-dim)",
                    color: s === "SPECIALIST" ? "var(--blue)" : "var(--green)",
                  }}
                >
                  {s}
                </span>
              ))}
              {traits.map((t) => {
                const ts = TRAIT_STYLE[t] || {
                  label: t,
                  color: "var(--text-secondary)",
                  bg: "var(--bg-secondary)",
                };
                return (
                  <span
                    key={t}
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: 0.5,
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: ts.bg,
                      color: ts.color,
                    }}
                  >
                    {ts.label.toUpperCase()}
                  </span>
                );
              })}
            </div>

            <div
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                marginTop: 8,
              }}
            >
              {archetype.description}
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <a
              href={`https://polymarket.com/profile/${wallet}`}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 11,
                color: "var(--blue)",
                padding: "4px 10px",
                border: "1px solid var(--border)",
                borderRadius: 6,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              View on Polymarket ↗
            </a>
            <button
              onClick={onClose}
              style={{
                background: "transparent",
                border: "1px solid var(--border)",
                color: "var(--text-secondary)",
                borderRadius: 6,
                padding: "4px 10px",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* ── Scrollable body ──────────────────────────────── */}
        <div style={{ overflowY: "auto", padding: "18px 22px" }}>
          {loading && !data && (
            <div style={{ color: "var(--text-secondary)" }}>Loading…</div>
          )}

          {data && !profile && (
            <div
              style={{
                padding: 16,
                borderRadius: 8,
                background: "var(--bg-card)",
                color: "var(--text-secondary)",
                fontSize: 12,
              }}
            >
              Esta wallet aún no ha sido enriquecida. El daemon la procesará según
              la cola de prioridades.
            </div>
          )}

          {profile && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* ── Stats widget (replaces old iframe) + KPI grid ── */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr",
                  gap: 14,
                  alignItems: "stretch",
                }}
              >
                <TraderStatsWidget wallet={wallet} width={340} height={380} />

                {/* KPI grid */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 10,
                    alignContent: "start",
                  }}
                >
                  <KpiBox
                    label="Cash Balance"
                    value={"—"}
                    note="Not tracked in our DB"
                  />
                  <KpiBox
                    label="Portfolio Value"
                    value={formatKpi(profile.estimated_portfolio_usd, "usd")}
                  />
                  <KpiBox
                    label="Open Positions"
                    value={String(profile.typical_n_simultaneous ?? "—")}
                    note="Typical simultaneous"
                  />
                  <KpiBox
                    label="Total PnL"
                    value={formatKpi(metrics?.pnl_30d, "usd")}
                    note="Last 30d"
                    color={numberOrNull(metrics?.pnl_30d)}
                  />
                  <KpiBox
                    label="Lifetime Volume"
                    value={formatKpi(
                      ((metrics?.total_trades as number | undefined) ?? 0) *
                        ((metrics?.avg_position_size as number | undefined) ?? 0) || null,
                      "usd",
                    )}
                    note="Trades × avg size"
                  />
                  <KpiBox
                    label="Win Rate"
                    value={formatKpi(metrics?.win_rate, "pct")}
                    note={
                      metrics?.total_trades != null
                        ? `${metrics.total_trades} trades`
                        : undefined
                    }
                  />
                </div>
              </div>

              {/* ── Trader Fact Sheet ──────────────────────── */}
              <Section title="Trader Fact Sheet" icon="🧾">
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 8,
                  }}
                >
                  <FactRow label="Top Category" value={String(profile.primary_universe ?? "—")} />
                  <FactRow label="Biggest Win" value="—" note="Phase 2" />
                  <FactRow label="Biggest Loss" value="—" note="Phase 2" />
                  <FactRow label="Avg Position" value={formatKpi(profile.avg_position_size_usd, "usd")} />
                  <FactRow
                    label="Avg Hold Time"
                    value={formatHoldTime(profile.avg_hold_time_minutes as number | undefined)}
                  />
                  <FactRow label="Max Drawdown" value={formatKpi(profile.max_drawdown_estimated_pct, "pct")} />
                  <FactRow
                    label="Sharpe"
                    value={formatKpi(profile.sharpe_proxy, "num")}
                    highlight={
                      typeof profile.sharpe_proxy === "number" && profile.sharpe_proxy >= 1.5
                        ? "green"
                        : undefined
                    }
                  />
                  <FactRow label="Profit Factor" value={formatKpi(profile.best_type_profit_factor, "num")} />
                  <FactRow label="Alpha Score" value={formatKpi(profile.cross_universe_alpha, "num")} />
                  <FactRow
                    label="Peak Hour"
                    value={
                      profile.preferred_hour_utc != null
                        ? `${String(profile.preferred_hour_utc).padStart(2, "0")}:00 UTC`
                        : "—"
                    }
                  />
                  <FactRow
                    label="Active Since"
                    value={formatActiveSince(
                      (profile.detected_by_specialist_at as number | undefined) ??
                        (profile.detected_by_scalper_at as number | undefined),
                    )}
                  />
                  <FactRow
                    label="Unique Markets"
                    value={
                      profile.type_trade_counts
                        ? String(
                            Object.keys(profile.type_trade_counts as Record<string, number>).length,
                          )
                        : "—"
                    }
                  />
                </div>
              </Section>

              {/* ── Behavioral + Rankings side by side ─────── */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <Section title="Behavioral Patterns" icon="👁">
                  <BehaviorRow
                    label="Contrarian"
                    value={formatKpi(profile.contrarian_score, "num")}
                    subtitle="Buys below 20¢ or sells above 80¢"
                  />
                  <BehaviorRow
                    label="Entry Timing"
                    value={String(profile.market_age_preference ?? "—")}
                    subtitle={
                      profile.avg_entry_price_winners != null
                        ? `Avg entry: ${formatKpi(profile.avg_entry_price_winners, "num")} → exit: ${formatKpi(profile.avg_exit_price_winners, "num")}`
                        : undefined
                    }
                    highlight={profile.market_age_preference === "EARLY" ? "green" : undefined}
                  />
                  <BehaviorRow
                    label="Hit Rate Trend"
                    value={String(profile.hit_rate_trend ?? "—")}
                    subtitle={
                      profile.hit_rate_last_30d != null
                        ? `Last 30d: ${formatKpi(profile.hit_rate_last_30d, "pct")}`
                        : undefined
                    }
                  />
                  <BehaviorRow
                    label="Avg Position Size"
                    value={formatKpi(profile.avg_position_size_usd, "usd")}
                    subtitle={
                      profile.median_position_size_usd != null
                        ? `Median: ${formatKpi(profile.median_position_size_usd, "usd")}`
                        : undefined
                    }
                  />
                </Section>

                <Section title="Comparative Rankings" icon="🏆">
                  <RankingBar
                    label="Volume"
                    percentile={rankings?.volume_percentile ?? null}
                  />
                  <RankingBar
                    label="PnL Total"
                    percentile={rankings?.pnl_percentile ?? null}
                  />
                  <RankingBar
                    label="Win Rate"
                    percentile={rankings?.pnl_pct_percentile ?? null}
                  />
                  <RankingBar
                    label="Account Age"
                    percentile={rankings?.account_age_percentile ?? null}
                  />
                  {rankings && rankings.universe_size > 0 && (
                    <div
                      style={{
                        fontSize: 9,
                        color: "var(--text-secondary)",
                        marginTop: 6,
                        textAlign: "right",
                      }}
                    >
                      vs. {rankings.universe_size.toLocaleString()} tracked wallets
                    </div>
                  )}
                </Section>
              </div>

              {/* ── Coverage by type ────────────────────────── */}
              <Section title="Coverage by Universe / Type" icon="🌐">
                <UniverseTable profile={profile} />
              </Section>

              {/* ── Trade History (observed) ───────────────── */}
              <Section title="Observed Trade History (from our runs)" icon="📈">
                <TradeHistory wallet={wallet} />
              </Section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────

function RarityGem({ color, label }: { color: string; label: string }) {
  return (
    <span
      aria-label={label}
      title={label}
      style={{
        display: "inline-block",
        width: "0.8em",
        height: "0.8em",
        background: `linear-gradient(135deg, ${color} 0%, ${color}aa 50%, ${color} 100%)`,
        clipPath: "polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0 38%)",
        boxShadow: `0 0 6px ${color}aa, inset 0 0 2px rgba(255,255,255,0.5)`,
      }}
    />
  );
}

function Section({ title, icon, children }: { title: string; icon?: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--bg-card)",
        padding: 14,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 1,
          color: "var(--text-primary)",
          marginBottom: 10,
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {icon && <span style={{ fontSize: 12 }}>{icon}</span>}
        {title}
      </div>
      {children}
    </div>
  );
}

function KpiBox({
  label,
  value,
  note,
  color,
}: {
  label: string;
  value: string;
  note?: string;
  color?: number | null;
}) {
  const textColor =
    color == null
      ? "var(--text-primary)"
      : color > 0
      ? "var(--green)"
      : color < 0
      ? "var(--red)"
      : "var(--text-primary)";
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "var(--bg-card)",
        padding: 10,
      }}
    >
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          textTransform: "uppercase",
          letterSpacing: 1,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, marginTop: 2, color: textColor }}>
        {value}
      </div>
      {note && (
        <div style={{ fontSize: 9, color: "var(--text-secondary)", marginTop: 2 }}>
          {note}
        </div>
      )}
    </div>
  );
}

function FactRow({
  label,
  value,
  note,
  highlight,
}: {
  label: string;
  value: string;
  note?: string;
  highlight?: "green" | "red";
}) {
  const color =
    highlight === "green"
      ? "var(--green)"
      : highlight === "red"
      ? "var(--red)"
      : "var(--text-primary)";
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 6,
        padding: "8px 10px",
        background: "var(--bg-primary)",
      }}
    >
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          textTransform: "uppercase",
          letterSpacing: 1,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2, color }}>
        {value}
      </div>
      {note && (
        <div style={{ fontSize: 9, color: "var(--text-secondary)", fontStyle: "italic" }}>
          {note}
        </div>
      )}
    </div>
  );
}

function BehaviorRow({
  label,
  value,
  subtitle,
  highlight,
}: {
  label: string;
  value: string;
  subtitle?: string;
  highlight?: "green" | "red";
}) {
  const color =
    highlight === "green"
      ? "var(--green)"
      : highlight === "red"
      ? "var(--red)"
      : "var(--text-primary)";
  return (
    <div
      style={{
        padding: "8px 0",
        borderBottom: "1px dashed var(--border)",
      }}
    >
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          textTransform: "uppercase",
          letterSpacing: 1,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color }}>
        {value}
      </div>
      {subtitle && (
        <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2 }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

function RankingBar({
  label,
  percentile,
}: {
  label: string;
  percentile: number | null;
}) {
  const pct = percentile ?? 0;
  const color =
    percentile == null
      ? "var(--text-secondary)"
      : pct >= 80
      ? "var(--green)"
      : pct >= 50
      ? "var(--blue)"
      : pct >= 25
      ? "#f9a825"
      : "var(--red)";
  return (
    <div style={{ padding: "6px 0" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          fontSize: 11,
        }}
      >
        <span style={{ color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ fontWeight: 700, color }}>
          {percentile != null ? `${percentile}th percentile` : "—"}
        </span>
      </div>
      <div
        style={{
          marginTop: 3,
          height: 6,
          borderRadius: 3,
          background: "var(--bg-secondary)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            transition: "width 400ms ease-out",
          }}
        />
      </div>
    </div>
  );
}

function UniverseTable({ profile }: { profile: Record<string, unknown> }) {
  const hits = (profile.universe_hit_rates as Record<string, number>) || {};
  const pfs = (profile.universe_profit_factors as Record<string, number>) || {};
  const counts = (profile.universe_trade_counts as Record<string, number>) || {};
  const universes = Array.from(
    new Set([...Object.keys(hits), ...Object.keys(counts)]),
  );
  if (universes.length === 0) {
    return (
      <div style={{ fontSize: 11, color: "var(--text-secondary)", fontStyle: "italic" }}>
        Sin datos suficientes por universo.
      </div>
    );
  }

  return (
    <table style={{ width: "100%", fontSize: 11 }}>
      <thead>
        <tr style={{ color: "var(--text-secondary)", textAlign: "left" }}>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>Universe</th>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>HR</th>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>Profit Factor</th>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>Trades</th>
        </tr>
      </thead>
      <tbody>
        {universes.map((u) => {
          const hr = hits[u];
          const hrColor = hr >= 0.65 ? "var(--green)" : hr >= 0.5 ? "var(--text-primary)" : "var(--red)";
          return (
            <tr key={u} style={{ borderTop: "1px dashed var(--border)" }}>
              <td style={{ padding: "4px 0" }}>{u}</td>
              <td style={{ padding: "4px 0", color: hrColor, fontWeight: 600 }}>
                {formatKpi(hr, "pct")}
              </td>
              <td style={{ padding: "4px 0" }}>{formatKpi(pfs[u], "num")}</td>
              <td style={{ padding: "4px 0" }}>{counts[u] ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TradeHistory({ wallet }: { wallet: string }) {
  const [trades, setTrades] = useState<Record<string, unknown>[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(`/api/trades?source_wallet=${wallet}&limit=15`)
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (!cancelled) setTrades(Array.isArray(d) ? d : []);
      })
      .catch(() => {
        if (!cancelled) setTrades([]);
      });
    return () => {
      cancelled = true;
    };
  }, [wallet]);

  if (trades == null) return <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>Loading…</div>;
  if (trades.length === 0) {
    return (
      <div style={{ fontSize: 11, color: "var(--text-secondary)", fontStyle: "italic" }}>
        No hay trades observados de esta wallet en nuestros runs.
      </div>
    );
  }

  return (
    <table style={{ width: "100%", fontSize: 11 }}>
      <thead>
        <tr style={{ color: "var(--text-secondary)", textAlign: "left" }}>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>Date</th>
          <th style={{ padding: "4px 0", fontWeight: 500 }}>Market</th>
          <th style={{ padding: "4px 0", fontWeight: 500, textAlign: "center" }}>Side</th>
          <th style={{ padding: "4px 0", fontWeight: 500, textAlign: "right" }}>Entry</th>
          <th style={{ padding: "4px 0", fontWeight: 500, textAlign: "right" }}>Exit</th>
          <th style={{ padding: "4px 0", fontWeight: 500, textAlign: "right" }}>P&L</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => {
          const stamp = (t.closed_at as string) ?? (t.opened_at as string) ?? "";
          const pnl = Number(t.pnl_usd ?? 0);
          const pnlColor = pnl > 0 ? "var(--green)" : pnl < 0 ? "var(--red)" : "var(--text-secondary)";
          return (
            <tr key={String(t.id)} style={{ borderTop: "1px dashed var(--border)" }}>
              <td style={{ padding: "4px 0", color: "var(--text-secondary)" }}>
                {stamp.slice(5, 10)}
              </td>
              <td
                style={{ padding: "4px 0", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={String(t.market_question ?? "")}
              >
                {String(t.market_question ?? "")}
              </td>
              <td style={{ padding: "4px 0", textAlign: "center" }}>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    padding: "1px 5px",
                    borderRadius: 3,
                    background:
                      t.direction === "YES" ? "var(--green-dim)" : "var(--red-dim)",
                    color: t.direction === "YES" ? "var(--green)" : "var(--red)",
                  }}
                >
                  {String(t.direction ?? "")}
                </span>
              </td>
              <td style={{ padding: "4px 0", textAlign: "right" }}>
                ${Number(t.entry_price ?? 0).toFixed(3)}
              </td>
              <td style={{ padding: "4px 0", textAlign: "right" }}>
                {t.exit_price != null ? `$${Number(t.exit_price).toFixed(3)}` : "—"}
              </td>
              <td style={{ padding: "4px 0", textAlign: "right", color: pnlColor, fontWeight: 600 }}>
                {pnl > 0 ? "+" : ""}
                {pnl !== 0 ? `$${pnl.toFixed(2)}` : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Helpers ────────────────────────────────────────────────────

function numberOrNull(v: unknown): number | null {
  if (typeof v === "number" && isFinite(v)) return v;
  return null;
}

function formatHoldTime(mins: number | undefined): string {
  if (mins == null || !isFinite(mins)) return "—";
  if (mins < 1) return "<1m";
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h`;
  return `${(mins / 1440).toFixed(1)}d`;
}

function formatActiveSince(ts: number | undefined): string {
  if (!ts) return "—";
  // ts is unix seconds
  const d = new Date(ts * 1000);
  const days = Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
  const month = d.toLocaleString("en-US", { month: "short" });
  const year = d.getFullYear();
  return `${month} ${year} (${days}d)`;
}
