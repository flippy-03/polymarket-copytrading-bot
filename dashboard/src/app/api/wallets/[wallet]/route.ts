import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/wallets/[wallet]
 *
 * Returns the full wallet_profiles row for one wallet (every bloque of KPIs),
 * plus the latest wallet_metrics snapshot and current scalper/specialist
 * membership. Used by the drawer popup.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ wallet: string }> },
) {
  const { wallet } = await params;
  if (!wallet) return NextResponse.json({ error: "missing wallet" }, { status: 400 });

  // Full profile (select *)
  let profile: Record<string, unknown> | null = null;
  try {
    const { data } = await supabase
      .from("wallet_profiles")
      .select("*")
      .eq("wallet", wallet)
      .limit(1);
    profile = data?.[0] ?? null;
  } catch {
    // Table may not exist yet.
  }

  // Latest metrics snapshot
  const { data: metricsRow } = await supabase
    .from("wallet_metrics")
    .select("*")
    .eq("wallet_address", wallet)
    .order("snapshot_at", { ascending: false })
    .limit(1);

  // Membership tables
  const { data: scalper } = await supabase
    .from("scalper_pool")
    .select("status, sharpe_14d, rank_position, capital_allocated_usd, entered_at, exited_at")
    .eq("wallet_address", wallet)
    .is("exited_at", null)
    .limit(1);

  const { data: specialist } = await supabase
    .from("spec_ranking")
    .select("universe, specialist_score, hit_rate, rank_position, last_active_ts, current_streak")
    .eq("wallet", wallet);

  return NextResponse.json({
    wallet,
    profile,
    metrics: metricsRow?.[0] ?? null,
    scalper: scalper?.[0] ?? null,
    specialist_rows: specialist ?? [],
  });
}
