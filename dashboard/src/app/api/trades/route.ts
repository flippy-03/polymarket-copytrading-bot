import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const strategy = resolveStrategy(request);
  const status = searchParams.get("status"); // OPEN, CLOSED, or null (all)
  const since = searchParams.get("since");
  const limit = parseInt(searchParams.get("limit") ?? "100");

  let query = supabase
    .from("copy_trades")
    .select("*")
    .eq("strategy", strategy)
    .order("opened_at", { ascending: false })
    .limit(limit);

  if (status) query = query.eq("status", status);
  if (since) query = query.gte("opened_at", since);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const enriched = (data ?? []).map((t) => ({
    ...t,
    market_question:
      t.market_question ?? `${String(t.market_polymarket_id ?? "").slice(0, 12)}…`,
  }));

  return NextResponse.json(enriched);
}
