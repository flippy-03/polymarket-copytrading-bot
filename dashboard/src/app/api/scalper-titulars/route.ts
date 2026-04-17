import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

/**
 * GET /api/scalper-titulars
 *
 * Returns detailed state of all active titulars plus portfolio balance info.
 */
export async function GET(request: Request) {
  const runId = await resolveRunId(request, "SCALPER");
  if (!runId) {
    return NextResponse.json({ titulars: [], balance: null });
  }

  type PoolRow = Record<string, unknown>;

  // Fetch active titulars from scalper_pool
  const { data: poolRowsRaw } = await supabase
    .from("scalper_pool")
    .select(
      "wallet_address, status, composite_score, approved_market_types, " +
      "per_trader_loss_limit, per_trader_consecutive_losses, per_trader_is_broken, " +
      "consecutive_wins, allocation_pct, sharpe_14d, rank_position"
    )
    .eq("run_id", runId)
    .eq("status", "ACTIVE_TITULAR");
  const poolRows = (poolRowsRaw ?? []) as PoolRow[];

  // Fetch portfolio state
  const { data: portfolio } = await supabase
    .from("portfolio_state_ct")
    .select("*")
    .eq("strategy", "SCALPER")
    .eq("run_id", runId)
    .eq("is_shadow", false)
    .limit(1)
    .single();

  const currentCapital = Number(portfolio?.current_capital ?? 1000);
  const initialCapital = Number(portfolio?.initial_capital ?? 1000);
  const peakCapital = Number(portfolio?.peak_capital ?? currentCapital);
  const numTitulars = poolRows.length || 4;

  // Fetch open trades per titular
  const { data: openTrades } = await supabase
    .from("copy_trades")
    .select("source_wallet, position_usd, market_type")
    .eq("run_id", runId)
    .eq("strategy", "SCALPER")
    .eq("status", "OPEN")
    .eq("is_shadow", false);

  // Aggregate per-titular exposure
  const exposureByWallet: Record<string, { total: number; count: number; byType: Record<string, number> }> = {};
  for (const t of openTrades ?? []) {
    const w = t.source_wallet as string;
    if (!exposureByWallet[w]) {
      exposureByWallet[w] = { total: 0, count: 0, byType: {} };
    }
    const usd = Number(t.position_usd ?? 0);
    exposureByWallet[w].total += usd;
    exposureByWallet[w].count += 1;
    const mt = (t.market_type as string) || "unknown";
    exposureByWallet[w].byType[mt] = (exposureByWallet[w].byType[mt] || 0) + usd;
  }

  // Fetch enriched profiles for each titular
  const wallets = (poolRows ?? []).map((r) => r.wallet_address);
  const { data: profiles } = wallets.length
    ? await supabase
        .from("wallet_profiles")
        .select(
          "wallet, primary_archetype, rarity_tier, best_market_type, " +
          "best_type_hit_rate, momentum_score, hit_rate_trend, " +
          "last_30d_trades, estimated_portfolio_usd"
        )
        .in("wallet", wallets)
    : { data: [] };

  const profileMap = new Map(
    (profiles ?? []).map((p: Record<string, unknown>) => [p.wallet as string, p])
  );

  // Build titular detail objects
  const titulars = poolRows.map((row) => {
    const wallet = row.wallet_address as string;
    const exposure = exposureByWallet[wallet] || { total: 0, count: 0, byType: {} };
    const allocPct = Number(row.allocation_pct ?? 1 / numTitulars);
    const allocation = currentCapital * allocPct;
    const profile = profileMap.get(wallet) || {};

    return {
      wallet,
      composite_score: row.composite_score,
      approved_market_types: row.approved_market_types ?? [],
      allocation_pct: allocPct,
      allocation_usd: Math.round(allocation * 100) / 100,
      exposure_usd: Math.round(exposure.total * 100) / 100,
      remaining_usd: Math.round(Math.max(0, allocation - exposure.total) * 100) / 100,
      open_positions: exposure.count,
      exposure_by_type: exposure.byType,
      per_trader_loss_limit: row.per_trader_loss_limit,
      per_trader_consecutive_losses: row.per_trader_consecutive_losses,
      per_trader_is_broken: row.per_trader_is_broken,
      consecutive_wins: row.consecutive_wins,
      has_bonus: (Number(row.consecutive_wins) || 0) >= 3,
      // From enriched profile
      archetype: (profile as Record<string, unknown>).primary_archetype ?? null,
      rarity: (profile as Record<string, unknown>).rarity_tier ?? null,
      best_type_hit_rate: (profile as Record<string, unknown>).best_type_hit_rate ?? null,
      momentum_score: (profile as Record<string, unknown>).momentum_score ?? null,
      hit_rate_trend: (profile as Record<string, unknown>).hit_rate_trend ?? null,
    };
  });

  // Aggregate balance info
  const totalExposure = titulars.reduce((s, t) => s + t.exposure_usd, 0);

  // Exposure by market type across all titulars
  const typeExposure: Record<string, number> = {};
  for (const t of titulars) {
    for (const [mt, usd] of Object.entries(t.exposure_by_type)) {
      typeExposure[mt] = (typeExposure[mt] || 0) + (usd as number);
    }
  }

  // Covered market types
  const coveredTypes = new Set<string>();
  for (const t of titulars) {
    for (const mt of t.approved_market_types as string[]) {
      coveredTypes.add(mt);
    }
  }

  const drawdown = peakCapital > 0 ? (peakCapital - currentCapital) / peakCapital : 0;

  const balance = {
    current_capital: currentCapital,
    initial_capital: initialCapital,
    total_pnl: Number(portfolio?.total_pnl ?? 0),
    total_pnl_pct: Number(portfolio?.total_pnl_pct ?? 0),
    peak_capital: peakCapital,
    drawdown_pct: Math.round(drawdown * 10000) / 10000,
    total_exposure: Math.round(totalExposure * 100) / 100,
    exposure_pct: currentCapital > 0 ? Math.round((totalExposure / currentCapital) * 10000) / 10000 : 0,
    exposure_by_type: typeExposure,
    covered_market_types: [...coveredTypes].sort(),
    diversification_score: coveredTypes.size,
    consecutive_losses: Number(portfolio?.consecutive_losses ?? 0),
    is_circuit_broken: Boolean(portfolio?.is_circuit_broken),
    win_rate: Number(portfolio?.win_rate ?? 0),
    total_trades: Number(portfolio?.total_trades ?? 0),
  };

  return NextResponse.json({ titulars, balance });
}
