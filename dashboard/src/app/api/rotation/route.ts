import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

// Returns the rotation history + current scalper pool snapshot.
export async function GET() {
  const [{ data: history, error: histErr }, { data: pool, error: poolErr }] =
    await Promise.all([
      supabase
        .from("rotation_history")
        .select("id, rotation_at, reason, removed_titulars, new_titulars, pool_snapshot")
        .order("rotation_at", { ascending: false })
        .limit(50),
      supabase
        .from("scalper_pool")
        .select(
          "wallet_address, status, sharpe_14d, rank_position, capital_allocated_usd, consecutive_losses, entered_at",
        )
        .order("rank_position", { ascending: true, nullsFirst: false }),
    ]);

  if (histErr) return NextResponse.json({ error: histErr.message }, { status: 500 });
  if (poolErr) return NextResponse.json({ error: poolErr.message }, { status: 500 });

  return NextResponse.json({
    history: history ?? [],
    pool: pool ?? [],
  });
}
