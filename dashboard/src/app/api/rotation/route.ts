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
      "wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd, consecutive_losses, entered_at, run_id",
    )
    .order("rank_position", { ascending: true, nullsFirst: false });
  if (runId) poolQuery = poolQuery.eq("run_id", runId);

  const [{ data: history, error: histErr }, { data: pool, error: poolErr }] =
    await Promise.all([historyQuery, poolQuery]);

  if (histErr) return NextResponse.json({ error: histErr.message }, { status: 500 });
  if (poolErr) return NextResponse.json({ error: poolErr.message }, { status: 500 });

  return NextResponse.json({
    history: history ?? [],
    pool: pool ?? [],
  });
}
