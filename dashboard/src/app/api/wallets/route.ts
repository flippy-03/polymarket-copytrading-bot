import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Only the columns actually rendered by dashboard/src/app/wallets/page.tsx.
const METRIC_COLUMNS =
  "wallet_address,snapshot_at,win_rate,total_trades,pnl_30d,pnl_7d," +
  "profit_factor,avg_holding_days,trades_per_month,sharpe_14d,bot_score," +
  "tier1_pass,tier2_score";

type MetricRow = Record<string, unknown> & { wallet_address: string };

function dedupeLatest(rows: MetricRow[] | null): Map<string, MetricRow> {
  const latest = new Map<string, MetricRow>();
  for (const row of rows ?? []) {
    if (!latest.has(row.wallet_address)) latest.set(row.wallet_address, row);
  }
  return latest;
}

/**
 * Returns the latest wallet_metrics snapshot per wallet, filtered by membership
 * table (scalper_pool or spec_ranking). We query the tiny membership table
 * first and then fetch metrics for just those addresses.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = (searchParams.get("source") || "all").toLowerCase();
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  // ── Fetch membership list first (small result) ─────────────────
  let addresses: string[] = [];
  let scalperMap: Map<string, Record<string, unknown>> | null = null;
  let specialistMap: Map<string, Record<string, unknown>> | null = null;

  if (source === "scalper" || source === "all") {
    let poolQuery = supabase
      .from("scalper_pool")
      .select("wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd")
      .is("exited_at", null);
    if (runId) poolQuery = poolQuery.eq("run_id", runId);
    const { data: pool } = await poolQuery;
    scalperMap = new Map((pool ?? []).map((p) => [p.wallet_address as string, p]));
    addresses.push(...scalperMap.keys());
  }

  if (source === "specialist" || source === "all") {
    let srQuery = supabase
      .from("spec_ranking")
      .select("wallet, universe, rank_position, specialist_score");
    if (runId) srQuery = srQuery.eq("run_id", runId);
    const { data: sr } = await srQuery;
    specialistMap = new Map((sr ?? []).map((s) => [s.wallet as string, s]));
    addresses.push(...specialistMap.keys());
  }

  // Dedupe the address list.
  addresses = Array.from(new Set(addresses));

  if (addresses.length === 0) {
    return NextResponse.json([]);
  }

  // ── Fetch only the latest metrics for these specific wallets ────
  let metricsQuery = supabase
    .from("wallet_metrics")
    .select(METRIC_COLUMNS)
    .in("wallet_address", addresses)
    .order("snapshot_at", { ascending: false })
    .limit(500);
  if (runId) metricsQuery = metricsQuery.eq("run_id", runId);

  const { data: metrics, error } = await metricsQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const latestByWallet = dedupeLatest((metrics as unknown) as MetricRow[] | null);

  // ── Assemble output in the shape the page expects ──────────────
  const out: Record<string, unknown>[] = [];
  for (const addr of addresses) {
    const row = latestByWallet.get(addr) ?? { wallet_address: addr };
    const enriched: Record<string, unknown> = { ...row, wallet_address: addr };
    if (scalperMap?.has(addr)) enriched.scalper = scalperMap.get(addr);
    if (specialistMap?.has(addr)) enriched.specialist = specialistMap.get(addr);
    out.push(enriched);
  }

  return NextResponse.json(out);
}
