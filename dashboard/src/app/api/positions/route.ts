import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);

  let query = supabase
    .from("copy_trades")
    .select("*")
    .eq("status", "OPEN")
    .eq("strategy", strategy)
    .order("opened_at", { ascending: false });

  if (runId) query = query.eq("run_id", runId);

  const isShadow = isShadowFilter(shadowMode);
  if (isShadow !== null) query = query.eq("is_shadow", isShadow);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const enriched = (data ?? []).map((t) => {
    const entry = Number(t.entry_price ?? 0);
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
