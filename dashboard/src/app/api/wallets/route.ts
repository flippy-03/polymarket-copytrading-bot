import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Returns a flat listing of tracked wallets with their latest metrics snapshot
// for the selected strategy + run. `?source=basket|scalper|all` narrows it
// further by membership table.
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = (searchParams.get("source") || "all").toLowerCase();
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  let metricsQuery = supabase
    .from("wallet_metrics")
    .select("*")
    .order("snapshot_at", { ascending: false })
    .limit(1000);
  if (runId) metricsQuery = metricsQuery.eq("run_id", runId);

  const { data: metrics, error } = await metricsQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const latestByWallet = new Map<string, Record<string, unknown>>();
  for (const row of metrics ?? []) {
    const addr = row.wallet_address as string;
    if (!latestByWallet.has(addr)) latestByWallet.set(addr, row);
  }

  const out: Record<string, unknown>[] = [];
  for (const [addr, row] of latestByWallet) {
    out.push({ ...row, wallet_address: addr });
  }

  if (source === "scalper") {
    let poolQuery = supabase
      .from("scalper_pool")
      .select("wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd");
    if (runId) poolQuery = poolQuery.eq("run_id", runId);
    const { data: pool } = await poolQuery;
    const poolMap = new Map((pool ?? []).map((p) => [p.wallet_address as string, p]));
    return NextResponse.json(
      out
        .filter((r) => poolMap.has(r.wallet_address as string))
        .map((r) => ({ ...r, scalper: poolMap.get(r.wallet_address as string) })),
    );
  }

  if (source === "basket") {
    let bwQuery = supabase
      .from("basket_wallets")
      .select("wallet_address, basket_id, rank_position, rank_score")
      .is("exited_at", null);
    if (runId) bwQuery = bwQuery.eq("run_id", runId);
    const { data: bw } = await bwQuery;
    const bwMap = new Map((bw ?? []).map((b) => [b.wallet_address as string, b]));
    return NextResponse.json(
      out
        .filter((r) => bwMap.has(r.wallet_address as string))
        .map((r) => ({ ...r, basket: bwMap.get(r.wallet_address as string) })),
    );
  }

  return NextResponse.json(out);
}
