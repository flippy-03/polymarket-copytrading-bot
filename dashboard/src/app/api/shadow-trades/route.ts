import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status"); // OPEN | CLOSED | null = all
  const limit = parseInt(searchParams.get("limit") ?? "500");

  let query = supabase
    .from("shadow_trades")
    .select("*")
    .order("entry_at", { ascending: false })
    .limit(limit);

  if (status) query = query.eq("status", status);

  const { data: trades, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const rows = trades ?? [];

  // Enrich with market question
  const marketIds = [...new Set(rows.map((t) => t.market_id).filter(Boolean))];
  let markets: Record<string, string> = {};
  if (marketIds.length > 0) {
    const { data: mData } = await supabase
      .from("markets")
      .select("id, question")
      .in("id", marketIds);
    for (const m of mData ?? []) markets[m.id] = m.question;
  }

  const enriched = rows.map((t) => ({
    ...t,
    market_question: markets[t.market_id] ?? "",
  }));

  return NextResponse.json(enriched);
}
