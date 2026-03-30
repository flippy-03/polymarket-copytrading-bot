import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const now = new Date();
  const since24h = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
  const since1h = new Date(now.getTime() - 60 * 60 * 1000).toISOString();

  // Portfolio
  const { data: portData } = await supabase
    .from("portfolio_state")
    .select("*")
    .order("run_id", { ascending: false })
    .limit(1);
  const port = portData?.[0] ?? null;

  // Open trades
  const { data: openTrades } = await supabase
    .from("paper_trades")
    .select("id, direction, entry_price, position_usd, opened_at, market_id")
    .eq("status", "OPEN");

  // Shadow trades
  let shadowOpen: any[] = [];
  let shadowClosed: any[] = [];
  let shadowTableExists = true;
  try {
    const { data: so } = await supabase.from("shadow_trades").select("*").eq("status", "OPEN");
    const { data: sc } = await supabase
      .from("shadow_trades")
      .select("direction, pnl_usd, pnl_pct, close_reason, blocked_reason, entry_price")
      .eq("status", "CLOSED");
    shadowOpen = so ?? [];
    shadowClosed = sc ?? [];
  } catch {
    shadowTableExists = false;
  }

  // Activity last 24h
  const { data: signals24h } = await supabase
    .from("signals")
    .select("status, direction")
    .gte("created_at", since24h);

  const { data: trades24h } = await supabase
    .from("paper_trades")
    .select("status, direction, pnl_usd, close_reason")
    .gte("opened_at", since24h);

  // Collector freshness
  const { data: lastSnap } = await supabase
    .from("market_snapshots")
    .select("snapshot_at")
    .order("snapshot_at", { ascending: false })
    .limit(1);

  const { data: snaps1h } = await supabase
    .from("market_snapshots")
    .select("id")
    .gte("snapshot_at", since1h);

  const lastSnapAt = lastSnap?.[0]?.snapshot_at ?? null;
  // Supabase returns timestamps without 'Z' — force UTC parsing to avoid local-time offset
  const snapAgeMs = lastSnapAt
    ? now.getTime() - new Date(lastSnapAt.endsWith("Z") ? lastSnapAt : lastSnapAt + "Z").getTime()
    : null;
  const collectorOk = snapAgeMs !== null && snapAgeMs < 10 * 60 * 1000;

  // Issues
  const issues: string[] = [];
  if (!shadowTableExists) issues.push("shadow_trades table missing");
  if (!collectorOk) issues.push("collector sin actividad >10min");
  if (port?.is_circuit_broken) issues.push("circuit breaker activo");

  return NextResponse.json({
    timestamp: now.toISOString(),
    status: issues.length === 0 ? "OK" : "WARN",
    issues,
    portfolio: port
      ? {
          capital: port.current_capital,
          pnl: port.total_pnl,
          pnlPct: port.total_pnl_pct,
          winRate: port.win_rate,
          wins: port.winning_trades,
          losses: port.losing_trades,
          totalTrades: port.total_trades,
          openPositions: port.open_positions,
          maxOpenPositions: port.max_open_positions,
          maxDrawdown: port.max_drawdown,
          circuitBroken: port.is_circuit_broken,
          circuitBrokenUntil: port.circuit_broken_until,
          updatedAt: port.updated_at,
        }
      : null,
    openTrades: openTrades ?? [],
    shadow: {
      tableExists: shadowTableExists,
      open: shadowOpen.length,
      openTrades: shadowOpen,
      closed: shadowClosed.length,
      wins: shadowClosed.filter((s) => (s.pnl_usd ?? 0) > 0).length,
      winRate: shadowClosed.length > 0
        ? shadowClosed.filter((s) => (s.pnl_usd ?? 0) > 0).length / shadowClosed.length
        : null,
      totalPnl: shadowClosed.reduce((sum, s) => sum + (s.pnl_usd ?? 0), 0),
      byCloseReason: shadowClosed.reduce((acc: Record<string, number>, s) => {
        const r = s.close_reason ?? "?";
        acc[r] = (acc[r] ?? 0) + 1;
        return acc;
      }, {}),
    },
    activity24h: {
      signalsGenerated: signals24h?.length ?? 0,
      signalsByStatus: (signals24h ?? []).reduce((acc: Record<string, number>, s) => {
        acc[s.status] = (acc[s.status] ?? 0) + 1;
        return acc;
      }, {}),
      tradesOpened: (trades24h ?? []).filter((t) => t.status === "OPEN").length,
      tradesClosed: (trades24h ?? []).filter((t) => t.status === "CLOSED").length,
      closedTrades: (trades24h ?? []).filter((t) => t.status === "CLOSED"),
    },
    collector: {
      lastSnapAt,
      snapAgeSeconds: snapAgeMs !== null ? Math.round(snapAgeMs / 1000) : null,
      snapshotsLastHour: snaps1h?.length ?? 0,
      ok: collectorOk,
    },
  });
}
