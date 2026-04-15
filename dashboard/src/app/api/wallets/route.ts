import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

// Returns a flat listing of tracked wallets with their latest metrics snapshot.
// Can be filtered by ?source=basket|scalper|all.
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = (searchParams.get("source") || "all").toLowerCase();

  // Grab latest metrics snapshot per wallet.
  const { data: metrics, error } = await supabase
    .from("wallet_metrics")
    .select("*")
    .order("snapshot_at", { ascending: false })
    .limit(1000);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const latestByWallet = new Map<string, Record<string, unknown>>();
  for (const row of metrics ?? []) {
    const addr = row.wallet_address as string;
    if (!latestByWallet.has(addr)) latestByWallet.set(addr, row);
  }

  // Filter by source
  const out: Record<string, unknown>[] = [];
  for (const [addr, row] of latestByWallet) {
    out.push({ ...row, wallet_address: addr });
  }

  if (source === "scalper") {
    const { data: pool } = await supabase
      .from("scalper_pool")
      .select("wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd");
    const poolMap = new Map((pool ?? []).map((p) => [p.wallet_address as string, p]));
    return NextResponse.json(
      out
        .filter((r) => poolMap.has(r.wallet_address as string))
        .map((r) => ({ ...r, scalper: poolMap.get(r.wallet_address as string) })),
    );
  }

  if (source === "basket") {
    const { data: bw } = await supabase
      .from("basket_wallets")
      .select("wallet_address, basket_id, rank_position, rank_score")
      .is("exited_at", null);
    const bwMap = new Map((bw ?? []).map((b) => [b.wallet_address as string, b]));
    return NextResponse.json(
      out
        .filter((r) => bwMap.has(r.wallet_address as string))
        .map((r) => ({ ...r, basket: bwMap.get(r.wallet_address as string) })),
    );
  }

  return NextResponse.json(out);
}
