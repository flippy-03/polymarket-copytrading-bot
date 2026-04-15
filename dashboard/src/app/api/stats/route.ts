import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

type ClosedTrade = {
  pnl_usd: number | null;
  opened_at: string | null;
  closed_at: string | null;
  direction: string | null;
  close_reason: string | null;
  market_polymarket_id: string | null;
  market_question: string | null;
  is_shadow: boolean | null;
};

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);

  let query = supabase
    .from("copy_trades")
    .select(
      "pnl_usd, opened_at, closed_at, direction, close_reason, market_polymarket_id, market_question, is_shadow",
    )
    .eq("strategy", strategy)
    .eq("status", "CLOSED")
    .order("closed_at", { ascending: true });

  if (runId) query = query.eq("run_id", runId);
  const isShadow = isShadowFilter(shadowMode);
  if (isShadow !== null) query = query.eq("is_shadow", isShadow);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const closed = (data ?? []) as ClosedTrade[];

  const wins = closed.filter((t) => (t.pnl_usd ?? 0) > 0);
  const losses = closed.filter((t) => (t.pnl_usd ?? 0) <= 0);

  const avgWin =
    wins.length > 0 ? wins.reduce((s, t) => s + (t.pnl_usd ?? 0), 0) / wins.length : 0;
  const avgLoss =
    losses.length > 0 ? losses.reduce((s, t) => s + (t.pnl_usd ?? 0), 0) / losses.length : 0;

  const holdTimes = closed
    .filter((t): t is ClosedTrade & { opened_at: string; closed_at: string } =>
      Boolean(t.opened_at && t.closed_at),
    )
    .map((t) => (new Date(t.closed_at).getTime() - new Date(t.opened_at).getTime()) / 3_600_000);
  const avgHoldTime =
    holdTimes.length > 0 ? holdTimes.reduce((s, h) => s + h, 0) / holdTimes.length : 0;

  const yesTrades = closed.filter((t) => t.direction === "YES");
  const noTrades = closed.filter((t) => t.direction === "NO");
  const yesPnl = yesTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const noPnl = noTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const yesWinRate =
    yesTrades.length > 0
      ? yesTrades.filter((t) => (t.pnl_usd ?? 0) > 0).length / yesTrades.length
      : 0;
  const noWinRate =
    noTrades.length > 0
      ? noTrades.filter((t) => (t.pnl_usd ?? 0) > 0).length / noTrades.length
      : 0;

  const bestTrade = closed.reduce<ClosedTrade | null>(
    (best, t) => ((t.pnl_usd ?? 0) > (best?.pnl_usd ?? -Infinity) ? t : best),
    null,
  );
  const worstTrade = closed.reduce<ClosedTrade | null>(
    (worst, t) => ((t.pnl_usd ?? 0) < (worst?.pnl_usd ?? Infinity) ? t : worst),
    null,
  );

  const byCloseReason: Record<string, { count: number; pnl: number }> = {};
  for (const t of closed) {
    const reason = t.close_reason ?? "UNKNOWN";
    if (!byCloseReason[reason]) byCloseReason[reason] = { count: 0, pnl: 0 };
    byCloseReason[reason].count++;
    byCloseReason[reason].pnl += t.pnl_usd ?? 0;
  }

  const dailyPnl: Record<string, number> = {};
  for (const t of closed) {
    if (!t.closed_at) continue;
    const day = t.closed_at.slice(0, 10);
    dailyPnl[day] = (dailyPnl[day] ?? 0) + (t.pnl_usd ?? 0);
  }

  let cumPnl = 0;
  const equityCurve = closed.map((t) => {
    cumPnl += t.pnl_usd ?? 0;
    return {
      date: (t.closed_at ?? t.opened_at ?? "").slice(0, 16).replace("T", " "),
      pnl: Math.round(cumPnl * 100) / 100,
      trade_pnl: Math.round((t.pnl_usd ?? 0) * 100) / 100,
    };
  });

  return NextResponse.json({
    strategy,
    shadowMode,
    runId,
    totalTrades: closed.length,
    wins: wins.length,
    losses: losses.length,
    avgWin: Math.round(avgWin * 100) / 100,
    avgLoss: Math.round(avgLoss * 100) / 100,
    avgHoldTimeHours: Math.round(avgHoldTime * 10) / 10,
    byDirection: {
      YES: {
        count: yesTrades.length,
        pnl: Math.round(yesPnl * 100) / 100,
        winRate: Math.round(yesWinRate * 100),
      },
      NO: {
        count: noTrades.length,
        pnl: Math.round(noPnl * 100) / 100,
        winRate: Math.round(noWinRate * 100),
      },
    },
    bestTrade,
    worstTrade,
    byCloseReason,
    dailyPnl,
    equityCurve,
  });
}
