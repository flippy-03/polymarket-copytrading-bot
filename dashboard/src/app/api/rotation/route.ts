import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Returns the rotation history + current scalper pool snapshot scoped to the
// current (or selected) SCALPER run.
export async function GET(request: Request) {
  const runId = await resolveRunId(request, "SCALPER");

  let historyQuery = supabase
    .from("rotation_history")
    .select("id, rotation_at, reason, removed_titulars, new_titulars, pool_snapshot, run_id")
    .order("rotation_at", { ascending: false })
    .limit(50);
  if (runId) historyQuery = historyQuery.eq("run_id", runId);

  let poolQuery = supabase
    .from("scalper_pool")
    .select(
      "wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd, entered_at, run_id",
    )
    .order("rank_position", { ascending: true, nullsFirst: false });
  if (runId) poolQuery = poolQuery.eq("run_id", runId);

  // consecutive_losses is portfolio-level (not per-wallet). Fetch from portfolio_state_ct.
  let portfolioQuery = supabase
    .from("portfolio_state_ct")
    .select("consecutive_losses, is_circuit_broken")
    .eq("strategy", "SCALPER")
    .eq("is_shadow", false)
    .limit(1);
  if (runId) portfolioQuery = portfolioQuery.eq("run_id", runId);

  const [
    { data: history, error: histErr },
    { data: pool, error: poolErr },
    { data: portfolioRows },
  ] = await Promise.all([historyQuery, poolQuery, portfolioQuery]);

  if (histErr) return NextResponse.json({ error: histErr.message }, { status: 500 });
  if (poolErr) return NextResponse.json({ error: poolErr.message }, { status: 500 });

  const portfolio = portfolioRows?.[0] ?? null;

  return NextResponse.json({
    history: history ?? [],
    pool: pool ?? [],
    consecutive_losses: portfolio?.consecutive_losses ?? 0,
    is_circuit_broken: portfolio?.is_circuit_broken ?? false,
  });
}
