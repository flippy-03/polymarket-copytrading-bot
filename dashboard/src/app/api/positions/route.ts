import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);

  const { data, error } = await supabase
    .from("copy_trades")
    .select("*")
    .eq("status", "OPEN")
    .eq("strategy", strategy)
    .order("opened_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const enriched = (data ?? []).map((t) => {
    const entry = Number(t.entry_price ?? 0);
    // No live price source wired yet — show zero unrealized PnL for paper OPEN trades.
    return {
      ...t,
      market_question: t.market_question ?? `${String(t.market_polymarket_id ?? "").slice(0, 12)}…`,
      current_price: entry,
      unrealized_pnl: 0,
      unrealized_pnl_pct: 0,
    };
  });

  return NextResponse.json(enriched);
}
