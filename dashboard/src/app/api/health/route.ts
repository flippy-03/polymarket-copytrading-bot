import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const { data: portfolios } = await supabase
    .from("portfolio_state_ct")
    .select("strategy,run_id,is_shadow,current_capital,open_positions,is_circuit_broken,updated_at");
  const { data: openTrades } = await supabase
    .from("copy_trades")
    .select("strategy")
    .eq("status", "OPEN");

  const openByStrategy: Record<string, number> = {};
  for (const t of openTrades ?? []) {
    const s = t.strategy as string;
    openByStrategy[s] = (openByStrategy[s] ?? 0) + 1;
  }

  return NextResponse.json({
    ok: true,
    portfolios: portfolios ?? [],
    openByStrategy,
  });
}
