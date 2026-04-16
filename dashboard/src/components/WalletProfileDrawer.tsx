"use client";

import { useEffect, useState } from "react";
import {
  formatKpi,
  getArchetype,
  getRarity,
  RARITY_STYLE,
  TRAIT_STYLE,
} from "@/lib/archetypes";
import { PolymarketScanEmbed } from "./PolymarketScanEmbed";

type FullResponse = {
  wallet: string;
  profile: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  scalper: Record<string, unknown> | null;
  specialist_rows: Record<string, unknown>[];
};

type Props = {
  wallet: string | null;
  onClose: () => void;
};

/**
 * Slide-in drawer with the full enriched profile for one wallet.
 * Sections are collapsible; the polymarketscan iframe sits at the bottom for
 * quick external comparison.
 */
export function WalletProfileDrawer({ wallet, onClose }: Props) {
  const [data, setData] = useState<FullResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!wallet) {
      setData(null);
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
    return () => {
      cancelled = true;
    };
  }, [wallet]);

  if (!wallet) return null;

  const profile = data?.profile || null;
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
      {/* Overlay */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.55)",
          zIndex: 40,
        }}
      />
      {/* Panel */}
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          height: "100vh",
          width: "min(640px, 92vw)",
          background: "var(--bg-primary)",
          borderLeft: `2px solid ${rarityStyle.color}`,
          boxShadow: `-10px 0 30px rgba(0,0,0,0.4), ${rarityStyle.glow}`,
          zIndex: 50,
          overflowY: "auto",
          padding: "18px 22px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: "monospace", fontSize: 14 }}>{wallet}</div>
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
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
              <a
                href={`https://polymarket.com/profile/${wallet}`}
                target="_blank"
                rel="noreferrer"
                style={{
                  fontSize: 10,
                  color: "var(--blue)",
                  padding: "2px 8px",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  textDecoration: "none",
                }}
              >
                polymarket.com ↗
              </a>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginTop: 10,
              }}
            >
              <span style={{ fontSize: 20 }}>{archetype.icon}</span>
              <div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: archetype.color,
                  }}
                >
                  {archetype.label}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                  {archetype.hsClass} ·{" "}
                  <span style={{ color: rarityStyle.color, fontWeight: 700 }}>
                    {rarityStyle.label} {rarityStyle.stars}
                  </span>
                </div>
              </div>
            </div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 8 }}>
              {archetype.description}
            </div>
            {traits.length > 0 && (
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
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
            )}
          </div>
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

        {loading && !data && (
          <div style={{ marginTop: 20, color: "var(--text-secondary)" }}>Loading…</div>
        )}

        {data && !profile && (
          <div
            style={{
              marginTop: 16,
              padding: 12,
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
          <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 14 }}>
            <Section title="Overview">
              <KpiRow label="Confidence" value={profile.profile_confidence as string} />
              <KpiRow
                label="Data completeness"
                value={formatKpi(profile.data_completeness_pct, "pct")}
              />
              <KpiRow
                label="Trades analyzed"
                value={String(profile.trades_analyzed ?? "—")}
              />
              <KpiRow
                label="Positions analyzed"
                value={String(profile.positions_analyzed ?? "—")}
              />
              <KpiRow
                label="Priority score"
                value={formatKpi(profile.priority_score, "num")}
              />
              <KpiRow
                label="Specialist score"
                value={formatKpi(profile.specialist_score, "num")}
              />
              <KpiRow
                label="Scalper rank"
                value={String(profile.scalper_rank ?? "—")}
              />
            </Section>

            <Section title="Coverage by Universe / Type">
              <UniverseTable profile={profile} />
            </Section>

            <Section title="Position & Sizing">
              <KpiRow
                label="Avg position"
                value={formatKpi(profile.avg_position_size_usd, "usd")}
              />
              <KpiRow
                label="Median position"
                value={formatKpi(profile.median_position_size_usd, "usd")}
              />
              <KpiRow
                label="Size CV"
                value={formatKpi(profile.position_size_cv, "num")}
              />
              <KpiRow
                label="Conviction ratio"
                value={formatKpi(profile.size_conviction_ratio, "num")}
              />
              <KpiRow
                label="Max position %"
                value={formatKpi(profile.max_position_pct_of_portfolio, "pct")}
              />
              <KpiRow
                label="Concentration Gini"
                value={formatKpi(profile.concentration_gini, "num")}
              />
              <KpiRow
                label="Est. portfolio"
                value={formatKpi(profile.estimated_portfolio_usd, "usd")}
              />
              <KpiRow
                label="Typical simultaneous"
                value={formatKpi(profile.typical_n_simultaneous, "num")}
              />
            </Section>

            <Section title="Exit Behavior (MVP proxy)">
              <KpiRow
                label="Hold to resolution %"
                value={formatKpi(profile.hold_to_resolution_pct, "pct")}
              />
              <Note>
                Métricas completas (exit_quality, stop_loss_rate, profit_taking) diferidas a Phase 2.
              </Note>
            </Section>

            <Section title="Portfolio">
              <KpiRow
                label="Diversification"
                value={formatKpi(profile.market_diversification_score, "num")}
              />
              <KpiRow
                label="Sharpe proxy"
                value={formatKpi(profile.sharpe_proxy, "num")}
              />
              <KpiAlloc allocation={profile.universe_allocation as Record<string, number> | undefined} />
            </Section>

            <Section title="Temporal & Momentum">
              <KpiRow
                label="Last 30d trades"
                value={String(profile.last_30d_trades ?? "—")}
              />
              <KpiRow
                label="Last 7d trades"
                value={String(profile.last_7d_trades ?? "—")}
              />
              <KpiRow
                label="Momentum score"
                value={formatKpi(profile.momentum_score, "num")}
              />
              <KpiRow
                label="Trend"
                value={String(profile.hit_rate_trend ?? "—")}
              />
              <KpiRow
                label="Last 30d HR"
                value={formatKpi(profile.hit_rate_last_30d, "pct")}
              />
              <KpiRow
                label="Worst 30d HR"
                value={formatKpi(profile.worst_30d_hit_rate, "pct")}
              />
              <KpiRow
                label="Preferred hour UTC"
                value={String(profile.preferred_hour_utc ?? "—")}
              />
              <KpiRow
                label="Weekend ratio"
                value={formatKpi(profile.weekend_activity_ratio, "num")}
              />
            </Section>

            <Section title="External: polymarketscan">
              <PolymarketScanEmbed wallet={wallet} width={520} height={400} />
            </Section>
          </div>
        )}
      </div>
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--bg-card)",
        padding: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 1,
          color: "var(--text-secondary)",
          marginBottom: 8,
          textTransform: "uppercase",
        }}
      >
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{children}</div>
    </div>
  );
}

function KpiRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: 12,
        padding: "3px 0",
        borderBottom: "1px dashed var(--border)",
      }}
    >
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value || "—"}</span>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        color: "var(--text-secondary)",
        fontStyle: "italic",
        marginTop: 4,
      }}
    >
      {children}
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
    return <Note>Sin datos suficientes por universo.</Note>;
  }

  return (
    <table style={{ width: "100%", fontSize: 11 }}>
      <thead>
        <tr style={{ color: "var(--text-secondary)", textAlign: "left" }}>
          <th style={{ padding: "3px 0" }}>Universe</th>
          <th style={{ padding: "3px 0" }}>HR</th>
          <th style={{ padding: "3px 0" }}>PF</th>
          <th style={{ padding: "3px 0" }}>Trades</th>
        </tr>
      </thead>
      <tbody>
        {universes.map((u) => (
          <tr key={u} style={{ borderTop: "1px dashed var(--border)" }}>
            <td style={{ padding: "3px 0" }}>{u}</td>
            <td style={{ padding: "3px 0" }}>{formatKpi(hits[u], "pct")}</td>
            <td style={{ padding: "3px 0" }}>{formatKpi(pfs[u], "num")}</td>
            <td style={{ padding: "3px 0" }}>{counts[u] ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KpiAlloc({
  allocation,
}: {
  allocation: Record<string, number> | undefined;
}) {
  if (!allocation || Object.keys(allocation).length === 0) return null;
  const entries = Object.entries(allocation).sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ marginTop: 4 }}>
      <div
        style={{
          fontSize: 10,
          color: "var(--text-secondary)",
          marginBottom: 3,
        }}
      >
        Universe allocation
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {entries.map(([u, pct]) => (
          <div
            key={u}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11,
            }}
          >
            <div style={{ width: 140, color: "var(--text-secondary)" }}>{u}</div>
            <div
              style={{
                flex: 1,
                height: 6,
                borderRadius: 3,
                background: "var(--bg-secondary)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.min(100, pct * 100)}%`,
                  height: "100%",
                  background: "var(--blue)",
                }}
              />
            </div>
            <div style={{ width: 40, textAlign: "right" }}>
              {(pct * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
