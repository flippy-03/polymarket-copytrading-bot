// Archetype mapping — Hearthstone TCG theme.
// Each primary archetype maps to a Hearthstone class with its canonical colour
// and icon. Signature KPIs are the 2-3 metrics that best identify the
// archetype on the card front.

export type ArchetypeId =
  | "HODLER"
  | "EDGE_HUNTER"
  | "SPECIALIST"
  | "GENERALIST"
  | "WHALE"
  | "SCALPER_PROFILE"
  | "SCALPER_BOT"
  | "BOT"
  | "MOMENTUM_CHASER"
  | "UNKNOWN";

export type RarityTier = "LEGENDARY" | "EPIC" | "RARE" | "COMMON";

export type SignatureKpi = {
  // Path into the wallet_profiles row. Nested paths use "." (e.g.
  // "type_hit_rates.crypto_above"). The renderer resolves these.
  field: string;
  label: string;
  format?: "pct" | "usd" | "num" | "text";
};

export type ArchetypeDef = {
  id: ArchetypeId;
  label: string;
  hsClass: string;     // Hearthstone class name (lore)
  icon: string;        // Unicode/emoji
  color: string;       // CSS color (hex) — used for class banner + dot
  colorDim: string;    // lighter shade for backgrounds
  description: string; // one-liner shown in cards/drawers
  signature: SignatureKpi[]; // 2-3 KPIs highlighted on the card front
};

// Colours chosen to evoke each Hearthstone class while still working against
// the dark dashboard theme. `color` = main accent, `colorDim` = low-opacity
// variant for backgrounds.
export const ARCHETYPES: Record<ArchetypeId, ArchetypeDef> = {
  EDGE_HUNTER: {
    id: "EDGE_HUNTER",
    label: "Edge Hunter",
    hsClass: "Hunter",
    icon: "🏹",
    color: "#3a8c3a",
    colorDim: "rgba(58,140,58,0.15)",
    description: "Entra temprano con edge real sobre el mercado.",
    signature: [
      { field: "avg_implied_edge_at_entry", label: "Implied edge", format: "pct" },
      { field: "market_age_preference", label: "Entry timing", format: "text" },
      { field: "early_entry_pct", label: "Early entries", format: "pct" },
    ],
  },
  HODLER: {
    id: "HODLER",
    label: "Hodler",
    hsClass: "Paladin",
    icon: "🛡",
    color: "#d4b13b",
    colorDim: "rgba(212,177,59,0.15)",
    description: "Aguanta hasta resolución con convicción y disciplina.",
    signature: [
      { field: "hold_to_resolution_pct", label: "Hold-to-res", format: "pct" },
      { field: "best_type_hit_rate", label: "Best HR", format: "pct" },
      { field: "sharpe_proxy", label: "Sharpe proxy", format: "num" },
    ],
  },
  SPECIALIST: {
    id: "SPECIALIST",
    label: "Specialist",
    hsClass: "Priest",
    icon: "✨",
    color: "#e8e8e8",
    colorDim: "rgba(232,232,232,0.10)",
    description: "Nicho profundo: domina uno o dos tipos de mercado.",
    signature: [
      { field: "best_market_type", label: "Best type", format: "text" },
      { field: "best_type_hit_rate", label: "HR", format: "pct" },
      { field: "domain_expertise_breadth", label: "Breadth", format: "num" },
    ],
  },
  GENERALIST: {
    id: "GENERALIST",
    label: "Generalist",
    hsClass: "Mage",
    icon: "🔮",
    color: "#2b8fd9",
    colorDim: "rgba(43,143,217,0.15)",
    description: "Multi-dominio: consistente en varios tipos de mercado.",
    signature: [
      { field: "domain_expertise_breadth", label: "Breadth", format: "num" },
      { field: "cross_universe_alpha", label: "Cross-uni α", format: "num" },
      { field: "domain_agnostic_score", label: "Consistency", format: "num" },
    ],
  },
  WHALE: {
    id: "WHALE",
    label: "Whale",
    hsClass: "Warrior",
    icon: "⚔",
    color: "#c8322b",
    colorDim: "rgba(200,50,43,0.15)",
    description: "Capital grande, tamaños agresivos.",
    signature: [
      { field: "estimated_portfolio_usd", label: "Portfolio", format: "usd" },
      { field: "max_position_pct_of_portfolio", label: "Max pos", format: "pct" },
      { field: "typical_n_simultaneous", label: "Avg simul", format: "num" },
    ],
  },
  SCALPER_PROFILE: {
    id: "SCALPER_PROFILE",
    label: "Scalper",
    hsClass: "Druid",
    icon: "🌿",
    color: "#9a6a3b",
    colorDim: "rgba(154,106,59,0.15)",
    description: "Alta frecuencia, tamaños pequeños, rotación rápida.",
    signature: [
      { field: "last_30d_trades", label: "30d trades", format: "num" },
      { field: "avg_position_size_usd", label: "Avg size", format: "usd" },
      { field: "momentum_score", label: "Momentum", format: "num" },
    ],
  },
  SCALPER_BOT: {
    id: "SCALPER_BOT",
    label: "Scalper Bot",
    hsClass: "Warlock",
    icon: "⚡",
    color: "#c0392b",
    colorDim: "rgba(192,57,43,0.15)",
    description: "Hold time <5min. Scalper/HFT — no copia señales de predicción válidas.",
    signature: [
      { field: "avg_hold_time_minutes", label: "Avg hold", format: "num" },
      { field: "hr_cashpnl_confirmed_pct", label: "HR confirmado", format: "pct" },
      { field: "last_30d_trades", label: "30d trades", format: "num" },
    ],
  },
  BOT: {
    id: "BOT",
    label: "Bot",
    hsClass: "Warlock",
    icon: "💀",
    color: "#7e3ba3",
    colorDim: "rgba(126,59,163,0.15)",
    description: "Automatizado. CV de tamaño/intervalo sospechosamente uniforme.",
    signature: [
      { field: "position_size_cv", label: "Size CV", format: "num" },
      { field: "last_30d_trades", label: "30d trades", format: "num" },
      { field: "preferred_hour_utc", label: "Peak hour UTC", format: "num" },
    ],
  },
  MOMENTUM_CHASER: {
    id: "MOMENTUM_CHASER",
    label: "Momentum Chaser",
    hsClass: "Shaman",
    icon: "🌊",
    color: "#2a5aa0",
    colorDim: "rgba(42,90,160,0.15)",
    description: "Entra tarde, sigue tendencias, poca edge de información.",
    signature: [
      { field: "market_age_preference", label: "Entry timing", format: "text" },
      { field: "avg_entry_price_winners", label: "Avg entry", format: "num" },
      { field: "last_30d_trades", label: "30d trades", format: "num" },
    ],
  },
  UNKNOWN: {
    id: "UNKNOWN",
    label: "Unknown",
    hsClass: "Neutral",
    icon: "❓",
    color: "#6b7280",
    colorDim: "rgba(107,114,128,0.10)",
    description: "Perfil aún no enriquecido.",
    signature: [],
  },
};

// Rarity — borde del cromo + sombra sutil.
export const RARITY_STYLE: Record<
  RarityTier,
  { color: string; glow: string; label: string; stars: string }
> = {
  LEGENDARY: {
    color: "#f5a623",
    glow: "0 0 14px rgba(245,166,35,0.55), 0 0 4px rgba(245,166,35,0.35) inset",
    label: "Legendary",
    stars: "★★★★★",
  },
  EPIC: {
    color: "#a855f7",
    glow: "0 0 10px rgba(168,85,247,0.45), 0 0 3px rgba(168,85,247,0.30) inset",
    label: "Epic",
    stars: "★★★★",
  },
  RARE: {
    color: "#2b8fd9",
    glow: "0 0 8px rgba(43,143,217,0.35)",
    label: "Rare",
    stars: "★★★",
  },
  COMMON: {
    color: "#6b7280",
    glow: "none",
    label: "Common",
    stars: "★",
  },
};

// Traits — small chips below signature.
export const TRAIT_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  HOT: { label: "Hot", color: "#f97316", bg: "rgba(249,115,22,0.15)" },
  COLD: { label: "Cold", color: "#60a5fa", bg: "rgba(96,165,250,0.15)" },
  CONTRARIAN: { label: "Contrarian", color: "#c084fc", bg: "rgba(192,132,252,0.15)" },
  DISCIPLINED: { label: "Disciplined", color: "#34d399", bg: "rgba(52,211,153,0.15)" },
};

export function getArchetype(id: string | null | undefined): ArchetypeDef {
  if (!id) return ARCHETYPES.UNKNOWN;
  return ARCHETYPES[id as ArchetypeId] || ARCHETYPES.UNKNOWN;
}

export function getRarity(tier: string | null | undefined): RarityTier {
  if (tier === "LEGENDARY" || tier === "EPIC" || tier === "RARE" || tier === "COMMON") {
    return tier;
  }
  return "COMMON";
}

// Format a signature KPI value for display on the card.
export function formatKpi(
  value: unknown,
  format?: "pct" | "usd" | "num" | "text",
): string {
  if (value == null) return "—";
  if (format === "pct") {
    const n = typeof value === "number" ? value : Number(value);
    if (!isFinite(n)) return "—";
    // Values like 0.68 → "68%"; values already in percent units (>1.5) fall back to raw.
    return Math.abs(n) <= 1.5 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(1)}%`;
  }
  if (format === "usd") {
    const n = typeof value === "number" ? value : Number(value);
    if (!isFinite(n)) return "—";
    if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
    return `$${n.toFixed(0)}`;
  }
  if (format === "num") {
    const n = typeof value === "number" ? value : Number(value);
    if (!isFinite(n)) return String(value);
    if (Math.abs(n) < 10) return n.toFixed(2);
    return n.toFixed(0);
  }
  return String(value);
}

// Resolve a dotted field path against a row.
export function getField(
  row: Record<string, unknown> | null | undefined,
  path: string,
): unknown {
  if (!row) return null;
  const parts = path.split(".");
  let cur: unknown = row;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return null;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}
