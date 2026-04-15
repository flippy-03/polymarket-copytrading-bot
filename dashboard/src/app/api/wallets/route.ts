import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Only the columns actually rendered by dashboard/src/app/wallets/page.tsx.
// `select("*")` here previously cost ~740 KB per request.
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
 * table (scalper_pool or basket_wallets). We query the tiny membership table
 * first (7-21 rows) and then fetch metrics for just those addresses — payload
 * drops from ~740 KB to ~5 KB.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = (searchParams.get("source") || "all").toLowerCase();
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  // ── Fetch membership list first (small result) ─────────────────
  let addresses: string[] = [];
  let scalperMap: Map<string, Record<string, unknown>> | null = null;
  let basketMap: Map<string, Record<string, unknown>> | null = null;

  if (source === "scalper" || source === "all") {
    let poolQuery = supabase
      .from("scalper_pool")
      .select("wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd");
    if (runId) poolQuery = poolQuery.eq("run_id", runId);
    const { data: pool } = await poolQuery;
    scalperMap = new Map((pool ?? []).map((p) => [p.wallet_address as string, p]));
    addresses.push(...scalperMap.keys());
  }

  if (source === "basket" || source === "all") {
    let bwQuery = supabase
      .from("basket_wallets")
      .select("wallet_address, basket_id, rank_position, rank_score")
      .is("exited_at", null);
    if (runId) bwQuery = bwQuery.eq("run_id", runId);
    const { data: bw } = await bwQuery;
    basketMap = new Map((bw ?? []).map((b) => [b.wallet_address as string, b]));
    addresses.push(...basketMap.keys());
  }

  // Dedupe the address list (basket + scalper may overlap).
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
    // Max ~12 snapshots × 21 wallets = 252 rows; bounded.
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
    if (basketMap?.has(addr)) enriched.basket = basketMap.get(addr);
    out.push(enriched);
  }

  return NextResponse.json(out);
}
