import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/wallets/[wallet]/stats
 *
 * Compact stats shape for TraderStatsWidget (native replacement for the old
 * polymarketscan embed). Pulls from wallet_metrics (authoritative) with
 * wallet_profiles as fallback for volume/markets info.
 *
 * Fields that can't be derived from either table are returned as null — the
 * widget renders them as "—".
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ wallet: string }> },
) {
  const { wallet } = await params;
  if (!wallet) return NextResponse.json({ error: "missing wallet" }, { status: 400 });

  // Latest metrics snapshot
  const { data: metricsRows } = await supabase
    .from("wallet_metrics")
    .select(
      "win_rate, total_trades, profit_factor, avg_position_size, pnl_30d, pnl_7d, track_record_days, sharpe_14d, market_categories",
    )
    .eq("wallet_address", wallet)
    .order("snapshot_at", { ascending: false })
    .limit(1);
  const metrics = metricsRows?.[0] ?? null;

  // Profile — has some complementary info (unique markets via type_trade_counts)
  let profile: Record<string, unknown> | null = null;
  try {
    const { data } = await supabase
      .from("wallet_profiles")
      .select(
        "best_type_hit_rate, type_trade_counts, trades_analyzed, avg_position_size_usd, estimated_portfolio_usd, last_30d_trades, detected_by_specialist_at, detected_by_scalper_at",
      )
      .eq("wallet", wallet)
      .limit(1);
    profile = (data?.[0] as Record<string, unknown>) ?? null;
  } catch {
    // table may not exist in early envs
  }

  // Derive unique markets from type_trade_counts keys (upper bound) or 0
  const typeCounts = (profile?.type_trade_counts as Record<string, number>) || {};
  const uniqueMarkets = Object.keys(typeCounts).length || null;

  // Total volume ≈ total_trades × avg_position_size  (wallet_metrics if available)
  const totalTrades =
    (metrics?.total_trades as number | undefined) ??
    (profile?.trades_analyzed as number | undefined) ??
    null;
  const avgSize =
    (metrics?.avg_position_size as number | undefined) ??
    (profile?.avg_position_size_usd as number | undefined) ??
    null;
  const totalVolume =
    totalTrades != null && avgSize != null ? totalTrades * avgSize : null;

  const winRate = (metrics?.win_rate as number | undefined) ?? null;
  const wins = winRate != null && totalTrades != null ? Math.round(winRate * totalTrades) : null;
  const losses = wins != null && totalTrades != null ? totalTrades - wins : null;

  // Total PnL = pnl_30d — best proxy we have. track_record_days tells us the
  // full horizon; pnl_30d is the rolling window used for current edge.
  const totalPnl = (metrics?.pnl_30d as number | undefined) ?? null;
  const estPortfolio = (profile?.estimated_portfolio_usd as number | undefined) ?? null;
  const roiPct =
    totalPnl != null && estPortfolio != null && estPortfolio > 0
      ? totalPnl / estPortfolio
      : null;

  return NextResponse.json({
    wallet,
    handle: null, // no handle in our DB — widget falls back to shortened wallet
    total_pnl: totalPnl,
    roi_pct: roiPct,
    win_rate: winRate,
    total_trades: totalTrades,
    total_volume_usd: totalVolume,
    wins,
    losses,
    unique_markets: uniqueMarkets,
    best_trade: null, // not stored — Phase 2
    worst_trade: null, // not stored — Phase 2
  });
}
