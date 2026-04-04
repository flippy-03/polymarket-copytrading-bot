import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status") ?? "ACTIVE";
  const limit = parseInt(searchParams.get("limit") ?? "20");

  const { data, error } = await supabase
    .from("signals")
    .select("*")
    .eq("status", status)
    .order("created_at", { ascending: false })
    .limit(limit);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fetch market questions
  const marketIds = [...new Set((data ?? []).map((s) => s.market_id))];
  let markets: Record<string, string> = {};
  if (marketIds.length > 0) {
    const { data: mData } = await supabase
      .from("markets")
      .select("id,question")
      .in("id", marketIds);
    for (const m of mData ?? []) {
      markets[m.id] = m.question;
    }
  }

  const enriched = (data ?? []).map((s) => ({
    ...s,
    market_question: markets[s.market_id] ?? s.market_id.slice(0, 12) + "...",
  }));

  return NextResponse.json(enriched);
}
