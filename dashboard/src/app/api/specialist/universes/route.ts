import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  // Open positions per universe (from copy_trades metadata.universe)
  const { data: openTrades } = await supabase
    .from("copy_trades")
    .select("metadata, position_usd, pnl_usd")
    .eq("strategy", "SPECIALIST")
    .eq("status", "OPEN")
    .eq("is_shadow", false);

  const universeSummary: Record<
    string,
    { open: number; capital_used: number; unrealized_pnl: number }
  > = {};

  for (const t of openTrades ?? []) {
    const universe = (t.metadata as Record<string, unknown>)?.universe as string ?? "unknown";
    if (!universeSummary[universe]) {
      universeSummary[universe] = { open: 0, capital_used: 0, unrealized_pnl: 0 };
    }
    universeSummary[universe].open += 1;
    universeSummary[universe].capital_used += Number(t.position_usd ?? 0);
    universeSummary[universe].unrealized_pnl += Number(t.pnl_usd ?? 0);
  }

  // Specialist counts per universe from spec_ranking
  let rankQuery = supabase
    .from("spec_ranking")
    .select("universe, wallet", { count: "exact" });
  if (runId) rankQuery = rankQuery.eq("run_id", runId);
  const { data: rankRows } = await rankQuery;

  const specialistCounts: Record<string, number> = {};
  for (const r of rankRows ?? []) {
    const u = r.universe as string;
    specialistCounts[u] = (specialistCounts[u] ?? 0) + 1;
  }

  const UNIVERSES = {
    crypto_above_below: { capital_pct: 0.40, max_slots: 3 },
    crypto_price_range: { capital_pct: 0.30, max_slots: 2 },
    sports_game_winner: { capital_pct: 0.30, max_slots: 2 },
  };

  const out = Object.entries(UNIVERSES).map(([universe, cfg]) => ({
    universe,
    capital_pct: cfg.capital_pct,
    max_slots: cfg.max_slots,
    open_slots: universeSummary[universe]?.open ?? 0,
    capital_used: universeSummary[universe]?.capital_used ?? 0,
    unrealized_pnl: universeSummary[universe]?.unrealized_pnl ?? 0,
    specialists_known: specialistCounts[universe] ?? 0,
  }));

  return NextResponse.json(out);
}
