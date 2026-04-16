"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAutoRefresh } from "@/lib/hooks";
import { ctxQueryString, useStrategy } from "@/lib/strategy-context";
import {
  formatKpi,
  getArchetype,
  getField,
  getRarity,
  RARITY_STYLE,
} from "@/lib/archetypes";
import { WalletProfileCard, WalletCardRow } from "@/components/WalletProfileCard";
import { WalletProfileDrawer } from "@/components/WalletProfileDrawer";
import { PolymarketScanEmbed } from "@/components/PolymarketScanEmbed";

type Profile = Record<string, unknown>;

type WalletRow = WalletCardRow & {
  win_rate?: number | null;
  total_trades?: number | null;
  pnl_30d?: number | null;
  pnl_7d?: number | null;
  sharpe_14d?: number | null;
  bot_score?: number | null;
  scalper?: {
    status?: string | null;
    sharpe_14d?: number | null;
    rank_position?: number | null;
    capital_allocated_usd?: number | null;
  } | null;
  specialist?: {
    universe?: string | null;
    rank_position?: number | null;
    specialist_score?: number | null;
  } | null;
};

type Coverage = {
  totals?: { specialist?: number; scalper?: number; enriched?: number };
  by_confidence?: Record<string, number>;
  by_archetype?: Record<string, number>;
  by_rarity?: Record<string, number>;
  enrichment_ready?: boolean;
};

type ViewMode = "list" | "cards";
type SortKey = "priority" | "best_hr" | "momentum" | "sharpe" | "trades";

const VIEW_KEY = "ct.walletsView";

export default function WalletsPage() {
  const { strategy, runId, shadowMode } = useStrategy();
  const source = strategy === "SCALPER" ? "scalper" : "specialist";
  const [view, setView] = useState<ViewMode>("list");
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [selectedWallet, setSelectedWallet] = useState<string | null>(null);
  const [archetypeFilter, setArchetypeFilter] = useState<string>("ALL");

  // Restore view preference
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(VIEW_KEY);
    if (saved === "list" || saved === "cards") setView(saved);
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(VIEW_KEY, view);
    }
  }, [view]);

  const ctx = ctxQueryString(strategy, runId, shadowMode);
  const fetcher = useCallback(
    () => fetch(`/api/wallets?${ctx}&source=${source}`).then((r) => r.json()),
    [ctx, source],
  );
  const { data, loading } = useAutoRefresh<WalletRow[]>(fetcher, 60000);

  const coverageFetcher = useCallback(
    () => fetch("/api/wallets/coverage").then((r) => r.json()),
    [],
  );
  const { data: coverage } = useAutoRefresh<Coverage>(coverageFetcher, 60000);

  const rows = useMemo(() => {
    let list = Array.isArray(data) ? [...data] : [];
    if (archetypeFilter !== "ALL") {
      list = list.filter(
        (r) => (r.profile?.primary_archetype as string) === archetypeFilter,
      );
    }
    const keys: Record<SortKey, (r: WalletRow) => number> = {
      priority: (r) => (r.profile?.priority_score as number) ?? -1,
      best_hr: (r) => (r.profile?.best_type_hit_rate as number) ?? -1,
      momentum: (r) => (r.profile?.momentum_score as number) ?? -999,
      sharpe: (r) => r.scalper?.sharpe_14d ?? r.sharpe_14d ?? -999,
      trades: (r) => r.total_trades ?? -1,
    };
    return list.sort((a, b) => keys[sortKey](b) - keys[sortKey](a));
  }, [data, sortKey, archetypeFilter]);

  const totalWallets =
    strategy === "SCALPER"
      ? coverage?.totals?.scalper ?? 0
      : coverage?.totals?.specialist ?? 0;
  const enriched = coverage?.totals?.enriched ?? 0;
  const legendaries = coverage?.by_rarity?.LEGENDARY ?? 0;
  const epics = coverage?.by_rarity?.EPIC ?? 0;

  return (
    <div className="space-y-4 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-bold">
            {strategy === "SCALPER" ? "Scalper Pool" : "Specialist Rankings"}
          </h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {totalWallets} wallets · {enriched} enriched ·{" "}
            <span style={{ color: RARITY_STYLE.LEGENDARY.color }}>
              {legendaries} legendary
            </span>{" "}
            ·{" "}
            <span style={{ color: RARITY_STYLE.EPIC.color }}>{epics} epic</span>
          </p>
          {coverage && !coverage.enrichment_ready && (
            <p
              className="text-xs mt-1"
              style={{ color: "var(--text-secondary)", opacity: 0.7 }}
            >
              (enricher aún no inicializado — aplica la migración 010 y arranca el daemon)
            </p>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs flex-wrap">
          {/* View toggle */}
          <div
            className="flex rounded overflow-hidden border"
            style={{ borderColor: "var(--border)" }}
          >
            {(["list", "cards"] as ViewMode[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className="px-3 py-1"
                style={{
                  background: view === v ? "var(--blue-dim)" : "var(--bg-card)",
                  color: view === v ? "var(--blue)" : "var(--text-secondary)",
                  fontWeight: view === v ? 700 : 400,
                }}
              >
                {v === "list" ? "List" : "Cards"}
              </button>
            ))}
          </div>

          {/* Sort */}
          <div className="flex items-center gap-1">
            <span style={{ color: "var(--text-secondary)" }}>Sort:</span>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="px-2 py-1 rounded"
              style={{
                background: "var(--bg-card)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
            >
              <option value="priority">Priority</option>
              <option value="best_hr">Best HR</option>
              <option value="momentum">Momentum</option>
              <option value="sharpe">Sharpe 14d</option>
              <option value="trades">Trades</option>
            </select>
          </div>

          {/* Archetype filter */}
          <div className="flex items-center gap-1">
            <span style={{ color: "var(--text-secondary)" }}>Archetype:</span>
            <select
              value={archetypeFilter}
              onChange={(e) => setArchetypeFilter(e.target.value)}
              className="px-2 py-1 rounded"
              style={{
                background: "var(--bg-card)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
            >
              <option value="ALL">All</option>
              <option value="EDGE_HUNTER">Edge Hunter</option>
              <option value="HODLER">Hodler</option>
              <option value="SPECIALIST">Specialist</option>
              <option value="GENERALIST">Generalist</option>
              <option value="WHALE">Whale</option>
              <option value="SCALPER_PROFILE">Scalper</option>
              <option value="BOT">Bot</option>
              <option value="MOMENTUM_CHASER">Momentum Chaser</option>
            </select>
          </div>
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

      {/* List view */}
      {view === "list" && rows.length > 0 && (
        <ListView rows={rows} strategy={strategy} onSelect={setSelectedWallet} />
      )}

      {/* Cards view */}
      {view === "cards" && rows.length > 0 && (
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          }}
        >
          {rows.map((r) => (
            <WalletProfileCard
              key={r.wallet_address}
              row={r}
              onClick={setSelectedWallet}
            />
          ))}
        </div>
      )}

      <WalletProfileDrawer
        wallet={selectedWallet}
        onClose={() => setSelectedWallet(null)}
      />
    </div>
  );
}

// ── List view component ─────────────────────────────────────────

function ListView({
  rows,
  strategy,
  onSelect,
}: {
  rows: WalletRow[];
  strategy: "SPECIALIST" | "SCALPER";
  onSelect: (wallet: string) => void;
}) {
  const [hoveredWallet, setHoveredWallet] = useState<string | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleEnter = (wallet: string, e: React.MouseEvent<HTMLTableRowElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = { x: Math.min(rect.right + 12, window.innerWidth - 440), y: rect.top };
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => {
      setHoveredWallet(wallet);
      setHoverPos(pos);
    }, 400);
  };

  const handleLeave = () => {
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    setHoveredWallet(null);
    setHoverPos(null);
  };

  return (
    <>
      <div
        className="rounded-xl border overflow-x-auto"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left" style={{ color: "var(--text-secondary)" }}>
              <th className="p-3">Wallet</th>
              <th className="p-3">Archetype</th>
              {strategy === "SCALPER" ? (
                <>
                  <th className="p-3">Rank</th>
                  <th className="p-3">Status</th>
                </>
              ) : (
                <>
                  <th className="p-3">Universe</th>
                  <th className="p-3">Spec. score</th>
                </>
              )}
              <th className="p-3">Best HR</th>
              {strategy === "SCALPER" ? (
                <>
                  <th className="p-3">Size conv.</th>
                  <th className="p-3">Hold-to-res</th>
                </>
              ) : (
                <>
                  <th className="p-3">Breadth</th>
                  <th className="p-3">Cross-uni α</th>
                </>
              )}
              <th className="p-3">Momentum</th>
              <th className="p-3">Conf.</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <ListRow
                key={r.wallet_address}
                row={r}
                strategy={strategy}
                onHoverStart={handleEnter}
                onHoverEnd={handleLeave}
                onClick={() => onSelect(r.wallet_address)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Hover popover with polymarketscan widget */}
      {hoveredWallet && hoverPos && (
        <div
          style={{
            position: "fixed",
            left: hoverPos.x,
            top: hoverPos.y,
            zIndex: 30,
            pointerEvents: "none",
          }}
        >
          <PolymarketScanEmbed wallet={hoveredWallet} width={420} height={400} hoverMode />
        </div>
      )}
    </>
  );
}

function ListRow({
  row,
  strategy,
  onHoverStart,
  onHoverEnd,
  onClick,
}: {
  row: WalletRow;
  strategy: "SPECIALIST" | "SCALPER";
  onHoverStart: (wallet: string, e: React.MouseEvent<HTMLTableRowElement>) => void;
  onHoverEnd: () => void;
  onClick: () => void;
}) {
  const profile = row.profile || null;
  const archetypeId = (profile?.primary_archetype as string) || "UNKNOWN";
  const archetype = getArchetype(archetypeId);
  const rarity = getRarity(profile?.rarity_tier as string);
  const rarityStyle = RARITY_STYLE[rarity];
  const bestHr = profile?.best_type_hit_rate as number | undefined;
  const momentum = profile?.momentum_score as number | undefined;
  const trend = profile?.hit_rate_trend as string | undefined;

  const universe =
    (profile?.primary_universe as string) ||
    row.specialist?.universe ||
    "—";

  // Rarity gives the row a subtle tint
  const tint =
    rarity === "LEGENDARY"
      ? "rgba(245,166,35,0.05)"
      : rarity === "EPIC"
        ? "rgba(168,85,247,0.05)"
        : "transparent";

  return (
    <tr
      className="border-t cursor-pointer"
      style={{
        borderColor: "var(--border)",
        background: tint,
      }}
      onMouseEnter={(e) => onHoverStart(row.wallet_address, e)}
      onMouseLeave={onHoverEnd}
      onClick={onClick}
    >
      <td className="p-3 font-mono">
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: archetype.color,
              display: "inline-block",
              flexShrink: 0,
            }}
            title={archetype.label}
          />
          <span>
            {row.wallet_address.slice(0, 6)}…{row.wallet_address.slice(-4)}
          </span>
          <a
            href={`https://polymarket.com/profile/${row.wallet_address}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{ color: "var(--blue)", textDecoration: "none", marginLeft: 2 }}
            title="Open on polymarket.com"
          >
            ↗
          </a>
        </div>
      </td>
      <td className="p-3">
        {profile ? (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              background: archetype.colorDim,
              color: archetype.color,
              letterSpacing: 0.5,
            }}
          >
            {archetype.icon} {archetype.label}
          </span>
        ) : (
          <span style={{ color: "var(--text-secondary)" }}>—</span>
        )}
      </td>
      {strategy === "SCALPER" ? (
        <>
          <td className="p-3">{row.scalper?.rank_position ?? "—"}</td>
          <td className="p-3" style={{ color: "var(--text-secondary)" }}>
            {row.scalper?.status ?? "—"}
          </td>
        </>
      ) : (
        <>
          <td className="p-3" style={{ color: "var(--text-secondary)" }}>
            {universe}
          </td>
          <td className="p-3">
            {formatKpi(profile?.specialist_score ?? row.specialist?.specialist_score, "num")}
          </td>
        </>
      )}
      <td className="p-3" style={{ color: "var(--green)" }}>
        {formatKpi(bestHr, "pct")}
      </td>
      {strategy === "SCALPER" ? (
        <>
          <td className="p-3">
            {formatKpi(profile?.size_conviction_ratio, "num")}
          </td>
          <td className="p-3">
            {formatKpi(profile?.hold_to_resolution_pct, "pct")}
          </td>
        </>
      ) : (
        <>
          <td className="p-3">{String(profile?.domain_expertise_breadth ?? "—")}</td>
          <td className="p-3">{formatKpi(profile?.cross_universe_alpha, "num")}</td>
        </>
      )}
      <td className="p-3">
        <MomentumCell momentum={momentum} trend={trend} />
      </td>
      <td className="p-3">
        <ConfidenceBadge value={profile?.profile_confidence as string} />
      </td>
      <td className="p-3">
        <span
          style={{
            fontSize: 10,
            color: rarityStyle.color,
            fontWeight: 700,
            letterSpacing: 1,
          }}
          title={rarityStyle.label}
        >
          {rarityStyle.stars}
        </span>
      </td>
    </tr>
  );
}

function MomentumCell({
  momentum,
  trend,
}: {
  momentum?: number;
  trend?: string;
}) {
  if (momentum == null) return <span>—</span>;
  const arrow =
    trend === "IMPROVING" ? "▲" : trend === "DECLINING" ? "▼" : "→";
  const color =
    trend === "IMPROVING"
      ? "var(--green)"
      : trend === "DECLINING"
        ? "var(--red)"
        : "var(--text-secondary)";
  return (
    <span style={{ color }}>
      {arrow} {(momentum * 100).toFixed(0)}%
    </span>
  );
}

function ConfidenceBadge({ value }: { value?: string | null }) {
  if (!value) return <span style={{ color: "var(--text-secondary)" }}>—</span>;
  const colors: Record<string, { fg: string; bg: string }> = {
    HIGH: { fg: "var(--green)", bg: "var(--green-dim)" },
    MEDIUM: { fg: "var(--blue)", bg: "var(--blue-dim)" },
    LOW: { fg: "var(--text-secondary)", bg: "var(--bg-secondary)" },
  };
  const c = colors[value] || colors.LOW;
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 700,
        padding: "2px 6px",
        borderRadius: 4,
        background: c.bg,
        color: c.fg,
      }}
    >
      {value}
    </span>
  );
}
