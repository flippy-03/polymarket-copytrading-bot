"use client";

import {
  formatKpi,
  getArchetype,
  getField,
  getRarity,
  RARITY_STYLE,
  TRAIT_STYLE,
} from "@/lib/archetypes";

type Profile = Record<string, unknown> & {
  wallet?: string;
};

export type WalletCardRow = {
  wallet_address: string;
  profile?: Profile | null;
  scalper?: { rank_position?: number | null; status?: string | null } | null;
  specialist?: {
    universe?: string | null;
    rank_position?: number | null;
    specialist_score?: number | null;
  } | null;
};

type Props = {
  row: WalletCardRow;
  onClick?: (wallet: string) => void;
};

function timeAgo(ts?: number | null): string {
  if (!ts) return "—";
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h`;
  return `${Math.floor(secs / 86400)}d`;
}

/**
 * Rarity gem — a colored diamond/rhombus shape that sits inline with text.
 * Height = 0.85em so it aligns optically with the capital letters of the
 * archetype label it follows.
 */
function RarityGem({ color, label }: { color: string; label: string }) {
  return (
    <span
      aria-label={label}
      title={label}
      style={{
        display: "inline-block",
        width: "0.75em",
        height: "0.75em",
        background: `linear-gradient(135deg, ${color} 0%, ${color}aa 50%, ${color} 100%)`,
        clipPath: "polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0 38%)",
        boxShadow: `0 0 6px ${color}aa, inset 0 0 2px rgba(255,255,255,0.5)`,
        marginLeft: 4,
        flexShrink: 0,
      }}
    />
  );
}

/**
 * Decorative bookmark ribbon in the top-right corner of the card. Uses the
 * archetype color (distinct visual channel from the rarity gem). Purely
 * visual — no click handler. Shift stars to the left of the header so they
 * don't overlap with it.
 */
function BookmarkCorner({ color }: { color: string }) {
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        top: -3,
        right: 14,
        width: 16,
        height: 24,
        background: `linear-gradient(180deg, ${color} 0%, ${color}cc 100%)`,
        clipPath: "polygon(0 0, 100% 0, 100% 100%, 50% 76%, 0 100%)",
        filter: `drop-shadow(0 2px 4px ${color}88)`,
        pointerEvents: "none",
      }}
    />
  );
}

export function WalletProfileCard({ row, onClick }: Props) {
  const profile = row.profile || null;
  const archetypeId = (profile?.primary_archetype as string) || "UNKNOWN";
  const archetype = getArchetype(archetypeId);
  const rarity = getRarity(profile?.rarity_tier as string);
  const rarityStyle = RARITY_STYLE[rarity];
  const traits: string[] = Array.isArray(profile?.archetype_traits)
    ? (profile!.archetype_traits as string[])
    : [];
  const strategies: string[] = Array.isArray(profile?.strategies_active)
    ? (profile!.strategies_active as string[])
    : [];
  // Fallback: derive from row if profile missing
  if (strategies.length === 0) {
    if (row.scalper) strategies.push("SCALPER");
    if (row.specialist) strategies.push("SPECIALIST");
  }

  const confidence = (profile?.profile_confidence as string) || "—";
  const enrichedAt = profile?.enriched_at as number | undefined;
  const shortWallet = `${row.wallet_address.slice(0, 6)}…${row.wallet_address.slice(-4)}`;
  const universe =
    (profile?.primary_universe as string) ||
    row.specialist?.universe ||
    "—";

  const bestTypeHr = profile?.best_type_hit_rate as number | undefined;
  const bestType = (profile?.best_market_type as string) || "—";
  const typeCounts = profile?.type_trade_counts as Record<string, number> | undefined;
  const bestTypeTrades = typeCounts?.[bestType];

  return (
    <button
      onClick={() => onClick?.(row.wallet_address)}
      className="text-left w-full"
      style={{
        position: "relative",
        borderRadius: 12,
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        transition: "transform 120ms ease, border-color 120ms ease",
        overflow: "visible", // let bookmark poke out
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "";
      }}
    >
      {/* Decorative bookmark in top-right corner */}
      <BookmarkCorner color={archetype.color} />

      <div
        style={{
          position: "relative",
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          minHeight: 280,
        }}
      >
        {/* ── Header banner ───────────────────────────────── */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 10px",
            // Right side padded extra so the stars don't sit under the bookmark
            paddingRight: 22,
            borderRadius: 8,
            background: archetype.colorDim,
            borderBottom: `1px solid ${archetype.color}44`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 18, flexShrink: 0 }}>{archetype.icon}</span>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: archetype.color,
                  display: "inline-flex",
                  alignItems: "center",
                }}
              >
                {archetype.label.toUpperCase()}
                <RarityGem color={rarityStyle.color} label={rarityStyle.label} />
              </div>
              <div style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: 0.5 }}>
                {archetype.hsClass}
              </div>
            </div>
          </div>
          {/* Stars on the RIGHT — extra padding on the banner keeps clear of the bookmark */}
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: rarityStyle.color,
              letterSpacing: 1,
              flexShrink: 0,
            }}
            title={rarityStyle.label}
          >
            {rarityStyle.stars}
          </span>
        </div>

        {/* ── Wallet + badges ─────────────────────────────── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-primary)" }}>
            {shortWallet}
          </div>
          <a
            href={`https://polymarket.com/profile/${row.wallet_address}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{
              fontSize: 11,
              color: "var(--blue)",
              textDecoration: "none",
              padding: "2px 6px",
              borderRadius: 4,
              border: "1px solid var(--border)",
            }}
            title="Open on polymarket.com"
          >
            ↗
          </a>
        </div>

        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {strategies.map((s) => (
            <span
              key={s}
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 0.5,
                padding: "2px 6px",
                borderRadius: 4,
                background: s === "SPECIALIST" ? "var(--blue-dim)" : "var(--green-dim)",
                color: s === "SPECIALIST" ? "var(--blue)" : "var(--green)",
              }}
            >
              {s}
            </span>
          ))}
        </div>

        {/* ── Domain ──────────────────────────────────────── */}
        <div style={{ fontSize: 10 }}>
          <div style={{ color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>
            Domain
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2, color: "var(--text-primary)" }}>
            {universe}
          </div>
          {bestType !== "—" && (
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
              {bestType} ·{" "}
              <span style={{ color: "var(--green)" }}>
                {bestTypeHr != null ? `${(bestTypeHr * 100).toFixed(0)}% HR` : "—"}
              </span>
              {bestTypeTrades != null && (
                <span style={{ color: "var(--text-secondary)" }}> · {bestTypeTrades}t</span>
              )}
            </div>
          )}
        </div>

        {/* ── Signature KPIs ──────────────────────────────── */}
        <div style={{ fontSize: 10 }}>
          <div style={{ color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>
            Signature
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
            {archetype.signature.map((kpi) => {
              const value = getField(profile, kpi.field);
              return (
                <div
                  key={kpi.field}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    borderBottom: "1px dashed var(--border)",
                    paddingBottom: 2,
                  }}
                >
                  <span style={{ color: "var(--text-secondary)", fontSize: 10 }}>
                    {kpi.label}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: 11 }}>
                    {formatKpi(value, kpi.format)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Traits ──────────────────────────────────────── */}
        {traits.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {traits.slice(0, 2).map((t) => {
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

        {/* ── Footer ──────────────────────────────────────── */}
        <div
          style={{
            fontSize: 9,
            color: "var(--text-secondary)",
            marginTop: "auto",
            borderTop: "1px solid var(--border)",
            paddingTop: 6,
          }}
        >
          {profile
            ? `${confidence} · enriched ${timeAgo(enrichedAt)} ago`
            : "Not yet enriched"}
        </div>
      </div>
    </button>
  );
}
