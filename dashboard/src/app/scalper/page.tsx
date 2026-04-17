"use client";

import { useCallback, useState } from "react";
import { useAutoRefresh, timeAgo } from "@/lib/hooks";
import { ctxQueryString, useStrategy } from "@/lib/strategy-context";

type Titular = {
  wallet: string;
  composite_score: number | null;
  approved_market_types: string[];
  allocation_pct: number;
  allocation_usd: number;
  exposure_usd: number;
  remaining_usd: number;
  open_positions: number;
  exposure_by_type: Record<string, number>;
  per_trader_loss_limit: number;
  per_trader_consecutive_losses: number;
  per_trader_is_broken: boolean;
  consecutive_wins: number;
  has_bonus: boolean;
  archetype: string | null;
  rarity: string | null;
  best_type_hit_rate: number | null;
  momentum_score: number | null;
  hit_rate_trend: string | null;
};

type Balance = {
  current_capital: number;
  initial_capital: number;
  total_pnl: number;
  total_pnl_pct: number;
  peak_capital: number;
  drawdown_pct: number;
  total_exposure: number;
  exposure_pct: number;
  exposure_by_type: Record<string, number>;
  covered_market_types: string[];
  diversification_score: number;
  consecutive_losses: number;
  is_circuit_broken: boolean;
  win_rate: number;
  total_trades: number;
};

type Config = Record<string, unknown>;

const RISK_COLOR = (pct: number, max: number) => {
  const ratio = pct / max;
  if (ratio < 0.5) return "var(--green)";
  if (ratio < 0.8) return "var(--yellow)";
  return "var(--red)";
};

export default function ScalperPage() {
  const { strategy, runId, shadowMode } = useStrategy();
  const ctx = ctxQueryString(strategy, runId, shadowMode);

  const titularsFetcher = useCallback(
    () => fetch(`/api/scalper-titulars?${ctx}`).then((r) => r.json()),
    [ctx],
  );
  const { data: titularsData } = useAutoRefresh<{ titulars: Titular[]; balance: Balance }>(
    titularsFetcher,
  );

  const configFetcher = useCallback(
    () => fetch(`/api/scalper-config?${ctx}`).then((r) => r.json()),
    [ctx],
  );
  const { data: configData } = useAutoRefresh<{ config: Config; updated_at: string | null }>(
    configFetcher,
    60000,
  );

  const titulars = titularsData?.titulars ?? [];
  const balance = titularsData?.balance;
  const config = configData?.config ?? {};

  const [editingConfig, setEditingConfig] = useState(false);
  const [configDraft, setConfigDraft] = useState<Config>({});

  const startEditing = () => {
    setConfigDraft({ ...config });
    setEditingConfig(true);
  };

  const saveConfig = async () => {
    await fetch(`/api/scalper-config?${ctx}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: configDraft }),
    });
    setEditingConfig(false);
  };

  return (
    <div style={{ padding: 20, maxWidth: 1200 }}>
      <h1 style={{ marginBottom: 4 }}>Scalper V2</h1>
      <p style={{ color: "var(--text-secondary)", marginBottom: 20, fontSize: 13 }}>
        Profile-based copy trading with market-type filtering
      </p>

      {/* ── Balance Overview ─────────────────────────────── */}
      {balance && <BalancePanel balance={balance} />}

      {/* ── Titulars ─────────────────────────────────────── */}
      <h2 style={{ marginTop: 24, marginBottom: 12 }}>Titulars</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))", gap: 12 }}>
        {titulars.map((t) => (
          <TitularCard key={t.wallet} titular={t} maxDrawdown={Number(config.max_drawdown_pct ?? 0.30)} />
        ))}
        {titulars.length === 0 && (
          <p style={{ color: "var(--text-secondary)", gridColumn: "1 / -1" }}>
            No active titulars. Run pool_selector to select from enriched profiles.
          </p>
        )}
      </div>

      {/* ── Exposure by Market Type ──────────────────────── */}
      {balance && Object.keys(balance.exposure_by_type).length > 0 && (
        <>
          <h2 style={{ marginTop: 24, marginBottom: 12 }}>Exposure by Vertical</h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {Object.entries(balance.exposure_by_type)
              .sort((a, b) => b[1] - a[1])
              .map(([type, usd]) => (
                <div
                  key={type}
                  style={{
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    padding: "8px 14px",
                    fontSize: 13,
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{type}</div>
                  <div style={{ color: "var(--text-secondary)" }}>
                    ${usd.toFixed(2)} ({((usd / balance.current_capital) * 100).toFixed(1)}%)
                  </div>
                </div>
              ))}
          </div>
        </>
      )}

      {/* ── Configuration ────────────────────────────────── */}
      <h2 style={{ marginTop: 24, marginBottom: 12 }}>
        Configuration
        {!editingConfig && (
          <button
            onClick={startEditing}
            style={{ marginLeft: 12, fontSize: 12, padding: "2px 10px", cursor: "pointer" }}
          >
            Edit
          </button>
        )}
      </h2>
      <ConfigTable
        config={editingConfig ? configDraft : config}
        editing={editingConfig}
        onChange={(k, v) => setConfigDraft((prev) => ({ ...prev, [k]: v }))}
        onSave={saveConfig}
        onCancel={() => setEditingConfig(false)}
      />
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────── */

function BalancePanel({ balance }: { balance: Balance }) {
  const pnlColor = balance.total_pnl >= 0 ? "var(--green)" : "var(--red)";
  const drawdownColor = balance.drawdown_pct > 0.20 ? "var(--red)" : balance.drawdown_pct > 0.10 ? "var(--yellow)" : "var(--green)";
  const cbColor = balance.is_circuit_broken ? "var(--red)" : "var(--green)";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
        gap: 10,
        marginBottom: 16,
      }}
    >
      <StatBox label="Capital" value={`$${balance.current_capital.toFixed(2)}`} />
      <StatBox label="P&L" value={`$${balance.total_pnl.toFixed(2)}`} color={pnlColor} sub={`${(balance.total_pnl_pct * 100).toFixed(1)}%`} />
      <StatBox label="Drawdown" value={`${(balance.drawdown_pct * 100).toFixed(1)}%`} color={drawdownColor} />
      <StatBox label="Exposure" value={`$${balance.total_exposure.toFixed(2)}`} sub={`${(balance.exposure_pct * 100).toFixed(1)}%`} />
      <StatBox label="Win Rate" value={`${(balance.win_rate * 100).toFixed(1)}%`} sub={`${balance.total_trades} trades`} />
      <StatBox label="CB Status" value={balance.is_circuit_broken ? "BROKEN" : "OK"} color={cbColor} sub={`${balance.consecutive_losses} losses`} />
      <StatBox label="Diversification" value={`${balance.diversification_score} types`} />
    </div>
  );
}

function StatBox({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 6, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color || "var(--text-primary)" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{sub}</div>}
    </div>
  );
}

function TitularCard({ titular: t, maxDrawdown }: { titular: Titular; maxDrawdown: number }) {
  const borderColor = t.per_trader_is_broken
    ? "var(--red)"
    : t.consecutive_wins >= 3
      ? "var(--green)"
      : "var(--border)";

  const trendIcon = t.hit_rate_trend === "IMPROVING" ? " ^" : t.hit_rate_trend === "DECLINING" ? " v" : "";

  return (
    <div
      style={{
        background: "var(--bg-secondary)",
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 600 }}>
          {t.wallet.slice(0, 6)}...{t.wallet.slice(-4)}
          <a
            href={`https://polymarket.com/profile/${t.wallet}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ marginLeft: 4, fontSize: 11, textDecoration: "none" }}
          >
            {"->"}
          </a>
        </div>
        {t.archetype && (
          <span style={{ fontSize: 11, background: "var(--bg-primary)", padding: "1px 6px", borderRadius: 4 }}>
            {t.archetype}
          </span>
        )}
      </div>

      {/* Approved types */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
        {t.approved_market_types.map((mt) => (
          <span
            key={mt}
            style={{
              fontSize: 10,
              padding: "1px 6px",
              borderRadius: 3,
              background: "var(--bg-primary)",
              border: "1px solid var(--border)",
            }}
          >
            {mt}
          </span>
        ))}
      </div>

      {/* Metrics */}
      <div style={{ fontSize: 12, lineHeight: 1.8 }}>
        <div>
          Score: <b>{t.composite_score?.toFixed(3) ?? "—"}</b>
          {t.has_bonus && <span style={{ color: "var(--green)", marginLeft: 4 }}>+BONUS</span>}
        </div>
        <div>
          Allocation: <b>${t.allocation_usd.toFixed(0)}</b> ({(t.allocation_pct * 100).toFixed(0)}%)
        </div>
        <div>
          Exposure: <b>${t.exposure_usd.toFixed(2)}</b> / ${t.allocation_usd.toFixed(0)}
          <span style={{ color: "var(--text-secondary)" }}> ({t.open_positions} pos)</span>
        </div>
        <div>
          Best HR: <b>{t.best_type_hit_rate ? `${(t.best_type_hit_rate * 100).toFixed(1)}%` : "—"}</b>
          {trendIcon && <span style={{ color: t.hit_rate_trend === "IMPROVING" ? "var(--green)" : "var(--red)" }}>{trendIcon}</span>}
        </div>
        <div>
          Losses: <b>{t.per_trader_consecutive_losses}</b> / {t.per_trader_loss_limit}
          {t.per_trader_is_broken && <span style={{ color: "var(--red)", marginLeft: 4 }}>CB ACTIVE</span>}
        </div>
        <div>
          Wins streak: <b>{t.consecutive_wins}</b>
        </div>
      </div>
    </div>
  );
}

const CONFIG_LABELS: Record<string, { label: string; type: "number" | "array" }> = {
  min_hit_rate: { label: "Min Hit Rate", type: "number" },
  min_trade_count: { label: "Min Trade Count", type: "number" },
  trade_pct: { label: "Trade % of Allocation", type: "number" },
  max_trade_pct: { label: "Max Trade %", type: "number" },
  max_drawdown_pct: { label: "Max Drawdown %", type: "number" },
  health_check_hours: { label: "Health Check (hours)", type: "number" },
  cooldown_days_base: { label: "Cooldown Base (days)", type: "number" },
  global_loss_limit: { label: "Global Loss Limit", type: "number" },
  priority_market_types: { label: "Priority Types", type: "array" },
};

function ConfigTable({
  config,
  editing,
  onChange,
  onSave,
  onCancel,
}: {
  config: Config;
  editing: boolean;
  onChange: (k: string, v: unknown) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th style={{ textAlign: "left", padding: "6px 8px" }}>Parameter</th>
            <th style={{ textAlign: "left", padding: "6px 8px" }}>Value</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(CONFIG_LABELS).map(([key, meta]) => (
            <tr key={key} style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "6px 8px", color: "var(--text-secondary)" }}>{meta.label}</td>
              <td style={{ padding: "6px 8px" }}>
                {editing ? (
                  <input
                    type="text"
                    value={
                      meta.type === "array"
                        ? JSON.stringify(config[key] ?? [])
                        : String(config[key] ?? "")
                    }
                    onChange={(e) => {
                      const val =
                        meta.type === "array"
                          ? (() => { try { return JSON.parse(e.target.value); } catch { return []; } })()
                          : Number(e.target.value);
                      onChange(key, val);
                    }}
                    style={{
                      width: "100%",
                      background: "var(--bg-primary)",
                      border: "1px solid var(--border)",
                      borderRadius: 4,
                      padding: "2px 6px",
                      color: "var(--text-primary)",
                    }}
                  />
                ) : meta.type === "array" ? (
                  JSON.stringify(config[key] ?? [])
                ) : (
                  String(config[key] ?? "—")
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button onClick={onSave} style={{ padding: "4px 16px", cursor: "pointer" }}>Save</button>
          <button onClick={onCancel} style={{ padding: "4px 16px", cursor: "pointer" }}>Cancel</button>
        </div>
      )}
    </div>
  );
}
