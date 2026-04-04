import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("run_id");

  let query = supabase
    .from("paper_trades")
    .select("*")
    .eq("status", "OPEN")
    .order("opened_at", { ascending: false });

  if (runId) query = query.eq("run_id", parseInt(runId));

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const marketIds = [...new Set((data ?? []).map((t) => t.market_id))];
  let marketInfo: Record<string, { question: string; yes_price: number }> = {};

  if (marketIds.length > 0) {
    const { data: mData } = await supabase
      .from("markets")
      .select("id,question,yes_price")
      .in("id", marketIds);
    for (const m of mData ?? []) {
      marketInfo[m.id] = { question: m.question, yes_price: m.yes_price };
    }
  }

  const enriched = (data ?? []).map((t) => {
    const info = marketInfo[t.market_id];
    const currentYesPrice = info?.yes_price ?? t.entry_price;
    const currentPrice =
      t.direction === "YES" ? currentYesPrice : 1 - currentYesPrice;
    const entryPrice = t.entry_price;
    const unrealizedPnl = (currentPrice - entryPrice) * t.shares;
    const unrealizedPnlPct =
      entryPrice > 0 ? ((currentPrice - entryPrice) / entryPrice) * 100 : 0;

    return {
      ...t,
      market_question: info?.question ?? t.market_id.slice(0, 12) + "...",
      current_price: currentPrice,
      unrealized_pnl: Math.round(unrealizedPnl * 100) / 100,
      unrealized_pnl_pct: Math.round(unrealizedPnlPct * 100) / 100,
    };
  });

  return NextResponse.json(enriched);
}
