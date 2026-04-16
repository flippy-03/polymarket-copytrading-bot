import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId, resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Only the columns actually rendered by the /wallets page (both List and Cards).
const METRIC_COLUMNS =
  "wallet_address,snapshot_at,win_rate,total_trades,pnl_30d,pnl_7d," +
  "profit_factor,avg_holding_days,trades_per_month,sharpe_14d,bot_score," +
  "tier1_pass,tier2_score";

// Subset of wallet_profiles fields used by List + Card headers. The drawer
// endpoint [wallet]/route.ts returns the full row.
const PROFILE_COLUMNS =
  "wallet,enriched_at,profile_confidence,data_completeness_pct," +
  "strategies_active,specialist_score,scalper_rank,scalper_status," +
  "primary_archetype,archetype_traits,rarity_tier,archetype_confidence," +
  "primary_universe,active_universes,best_market_type,best_type_hit_rate," +
  "best_type_profit_factor,domain_expertise_breadth,cross_universe_alpha," +
  "domain_agnostic_score,hold_to_resolution_pct,size_conviction_ratio," +
  "avg_position_size_usd,estimated_portfolio_usd,max_position_pct_of_portfolio," +
  "typical_n_simultaneous,sharpe_proxy,last_30d_trades,last_7d_trades," +
  "momentum_score,hit_rate_trend,hit_rate_last_30d,priority_score," +
  "type_hit_rates,type_trade_counts,avg_implied_edge_at_entry," +
  "market_age_preference,early_entry_pct";

type MetricRow = Record<string, unknown> & { wallet_address: string };

function dedupeLatest(rows: MetricRow[] | null): Map<string, MetricRow> {
  const latest = new Map<string, MetricRow>();
  for (const row of rows ?? []) {
    if (!latest.has(row.wallet_address)) latest.set(row.wallet_address, row);
  }
  return latest;
}

/**
 * GET /api/wallets
 *
 * Query params:
 *   source=scalper|specialist|all   (defaults to "all")
 *   run_id=...                      (optional; falls back to active run per strategy)
 *
 * Returns each wallet with:
 *   - base metrics from wallet_metrics
 *   - source-specific badge (scalper_pool or spec_ranking)
 *   - profile?: wallet_profiles row (undefined if not yet enriched)
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = (searchParams.get("source") || "all").toLowerCase();
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  let addresses: string[] = [];
  let scalperMap: Map<string, Record<string, unknown>> | null = null;
  let specialistMap: Map<string, Record<string, unknown>> | null = null;

  if (source === "scalper" || source === "all") {
    let poolQuery = supabase
      .from("scalper_pool")
      .select(
        "wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd",
      )
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

  addresses = Array.from(new Set(addresses));
  if (addresses.length === 0) return NextResponse.json([]);

  // Fetch latest metrics for these wallets.
  let metricsQuery = supabase
    .from("wallet_metrics")
    .select(METRIC_COLUMNS)
    .in("wallet_address", addresses)
    .order("snapshot_at", { ascending: false })
    .limit(500);
  if (runId) metricsQuery = metricsQuery.eq("run_id", runId);

  const { data: metrics, error } = await metricsQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const latestByWallet = dedupeLatest(
    (metrics as unknown) as MetricRow[] | null,
  );

  // Fetch enriched profiles (best-effort — if wallet_profiles doesn't exist yet
  // we just return rows without the profile attached).
  let profileMap = new Map<string, Record<string, unknown>>();
  try {
    const { data: profiles } = await supabase
      .from("wallet_profiles")
      .select(PROFILE_COLUMNS)
      .in("wallet", addresses);
    const rows = (profiles ?? []) as unknown as Array<
      Record<string, unknown> & { wallet: string }
    >;
    profileMap = new Map(rows.map((p) => [p.wallet, p]));
  } catch {
    // Table doesn't exist yet (pre-migration) — ignore silently.
  }

  const out: Record<string, unknown>[] = [];
  for (const addr of addresses) {
    const row = latestByWallet.get(addr) ?? { wallet_address: addr };
    const enriched: Record<string, unknown> = {
      ...row,
      wallet_address: addr,
    };
    if (scalperMap?.has(addr)) enriched.scalper = scalperMap.get(addr);
    if (specialistMap?.has(addr)) enriched.specialist = specialistMap.get(addr);
    if (profileMap.has(addr)) enriched.profile = profileMap.get(addr);
    out.push(enriched);
  }

  return NextResponse.json(out);
}
