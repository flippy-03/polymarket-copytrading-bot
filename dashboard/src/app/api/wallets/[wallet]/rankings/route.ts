import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/wallets/[wallet]/rankings
 *
 * Percentile rank of this wallet across the full wallet_metrics population,
 * for the four axes polymarketscan surfaces: volume, pnl, pnl %, account age.
 *
 * Computation: fetch all wallets' snapshot values for each metric, sort, find
 * this wallet's position → percentile = rank / total.
 *
 * This is computed server-side per request (no materialised view yet). With a
 * few thousand tracked wallets it's fast; if the table grows past tens of
 * thousands we should add a cached_rankings table updated hourly.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ wallet: string }> },
) {
  const { wallet } = await params;
  if (!wallet) return NextResponse.json({ error: "missing wallet" }, { status: 400 });

  // Grab every wallet's most recent metric row. Limit to 5000 to stay cheap.
  const { data: allMetrics } = await supabase
    .from("wallet_metrics")
    .select("wallet_address, pnl_30d, win_rate, total_trades, avg_position_size, track_record_days")
    .order("snapshot_at", { ascending: false })
    .limit(5000);

  type Row = {
    wallet_address: string;
    pnl_30d: number | null;
    win_rate: number | null;
    total_trades: number | null;
    avg_position_size: number | null;
    track_record_days: number | null;
  };
  const rows = (allMetrics ?? []) as Row[];

  // Keep the most recent snapshot per wallet (order already desc by snapshot_at).
  const byWallet = new Map<string, Row>();
  for (const r of rows) {
    if (!byWallet.has(r.wallet_address)) byWallet.set(r.wallet_address, r);
  }
  const dedup = Array.from(byWallet.values());
  const total = dedup.length;

  const me = byWallet.get(wallet);

  function percentile(axis: (r: Row) => number | null): number | null {
    if (!me) return null;
    const myVal = axis(me);
    if (myVal == null || !isFinite(myVal)) return null;
    const values = dedup
      .map((r) => axis(r))
      .filter((v): v is number => v != null && isFinite(v));
    if (values.length < 5) return null; // not enough data to rank
    const lower = values.filter((v) => v < myVal).length;
    return Math.round((lower / values.length) * 100);
  }

  const volumeAxis = (r: Row) =>
    r.total_trades != null && r.avg_position_size != null
      ? r.total_trades * r.avg_position_size
      : null;

  return NextResponse.json({
    wallet,
    universe_size: total,
    has_data: !!me,
    volume_percentile: percentile(volumeAxis),
    pnl_percentile: percentile((r) => r.pnl_30d),
    pnl_pct_percentile: percentile((r) => r.win_rate),
    account_age_percentile: percentile((r) => r.track_record_days),
  });
}
