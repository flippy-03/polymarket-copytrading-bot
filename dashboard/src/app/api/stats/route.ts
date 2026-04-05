import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("run_id");

  let query = supabase
    .from("paper_trades")
    .select("*")
    .eq("status", "CLOSED")
    .order("closed_at", { ascending: true });

  if (runId) query = query.eq("run_id", parseInt(runId));

  const { data: trades, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const closed = trades ?? [];

  const wins = closed.filter((t) => (t.pnl_usd ?? 0) > 0);
  const losses = closed.filter((t) => (t.pnl_usd ?? 0) <= 0);

  const avgWin = wins.length > 0
    ? wins.reduce((s, t) => s + (t.pnl_usd ?? 0), 0) / wins.length
    : 0;
  const avgLoss = losses.length > 0
    ? losses.reduce((s, t) => s + (t.pnl_usd ?? 0), 0) / losses.length
    : 0;

  const holdTimes = closed
    .filter((t) => t.opened_at && t.closed_at)
    .map((t) => {
      const open = new Date(t.opened_at).getTime();
      const close = new Date(t.closed_at).getTime();
      return (close - open) / (1000 * 60 * 60);
    });
  const avgHoldTime = holdTimes.length > 0
    ? holdTimes.reduce((s, h) => s + h, 0) / holdTimes.length
    : 0;

  const yesTrades = closed.filter((t) => t.direction === "YES");
  const noTrades = closed.filter((t) => t.direction === "NO");
  const yesPnl = yesTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const noPnl = noTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const yesWinRate = yesTrades.length > 0
    ? yesTrades.filter((t) => (t.pnl_usd ?? 0) > 0).length / yesTrades.length
    : 0;
  const noWinRate = noTrades.length > 0
    ? noTrades.filter((t) => (t.pnl_usd ?? 0) > 0).length / noTrades.length
    : 0;

  const bestTrade = closed.reduce(
    (best, t) => ((t.pnl_usd ?? 0) > (best?.pnl_usd ?? -Infinity) ? t : best),
    null as typeof closed[0] | null
  );
  const worstTrade = closed.reduce(
    (worst, t) => ((t.pnl_usd ?? 0) < (worst?.pnl_usd ?? Infinity) ? t : worst),
    null as typeof closed[0] | null
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
      date: (t.closed_at ?? t.opened_at).slice(0, 16).replace("T", " "),
      pnl: Math.round(cumPnl * 100) / 100,
      trade_pnl: Math.round((t.pnl_usd ?? 0) * 100) / 100,
    };
  });

  const ids = [bestTrade?.market_id, worstTrade?.market_id].filter(Boolean) as string[];
  let markets: Record<string, string> = {};
  if (ids.length > 0) {
    const { data: mData } = await supabase
      .from("markets")
      .select("id,question")
      .in("id", ids);
    for (const m of mData ?? []) markets[m.id] = m.question;
  }

  const { data: runsRaw } = await supabase
    .from("portfolio_state")
    .select("run_id,updated_at")
    .order("run_id", { ascending: false });
  const runs = (runsRaw ?? []).map((r) => ({ id: r.run_id, started_at: r.updated_at, note: "" }));

  return NextResponse.json({
    totalTrades: closed.length,
    wins: wins.length,
    losses: losses.length,
    avgWin: Math.round(avgWin * 100) / 100,
    avgLoss: Math.round(avgLoss * 100) / 100,
    avgHoldTimeHours: Math.round(avgHoldTime * 10) / 10,
    byDirection: {
      YES: { count: yesTrades.length, pnl: Math.round(yesPnl * 100) / 100, winRate: Math.round(yesWinRate * 100) },
      NO: { count: noTrades.length, pnl: Math.round(noPnl * 100) / 100, winRate: Math.round(noWinRate * 100) },
    },
    bestTrade: bestTrade ? { ...bestTrade, market_question: markets[bestTrade.market_id] ?? "" } : null,
    worstTrade: worstTrade ? { ...worstTrade, market_question: markets[worstTrade.market_id] ?? "" } : null,
    byCloseReason,
    dailyPnl,
    equityCurve,
    runs: runs ?? [],
  });
}
