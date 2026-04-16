import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const universe = searchParams.get("universe");
  const limit = Math.min(Number(searchParams.get("limit") ?? "20"), 100);
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  let q = supabase
    .from("spec_ranking")
    .select(
      "wallet, universe, hit_rate, specialist_score, universe_trades, " +
      "universe_wins, current_streak, last_active_ts, avg_position_usd, " +
      "rank_position, last_updated_ts"
    )
    .order("specialist_score", { ascending: false })
    .limit(limit);

  if (universe) q = q.eq("universe", universe);
  if (runId) q = q.eq("run_id", runId);

  const { data, error } = await q;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
