import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Consensus signals only apply to the BASKET strategy. The SCALPER strategy
// copies titulares in real-time and has no pending "signal" concept.
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const strategy = resolveStrategy(request);
  if (strategy !== "BASKET") return NextResponse.json([]);
  const runId = await resolveRunId(request, strategy);

  const status = searchParams.get("status") ?? "PENDING";
  const limit = parseInt(searchParams.get("limit") ?? "20");

  let query = supabase
    .from("consensus_signals")
    .select("*, baskets(category)")
    .eq("status", status)
    .order("created_at", { ascending: false })
    .limit(limit);

  if (runId) query = query.eq("run_id", runId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const enriched = (data ?? []).map((s: Record<string, unknown>) => ({
    ...s,
    basket_category: (s.baskets as { category?: string } | null)?.category ?? null,
    market_question:
      (s.market_question as string | null) ??
      `${String(s.market_polymarket_id ?? "").slice(0, 12)}…`,
  }));

  return NextResponse.json(enriched);
}
