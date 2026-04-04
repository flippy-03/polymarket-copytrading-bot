import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("run_id");
  const status = searchParams.get("status"); // OPEN, CLOSED, or null (all)
  const since = searchParams.get("since"); // ISO date string
  const limit = parseInt(searchParams.get("limit") ?? "100");

  let query = supabase
    .from("paper_trades")
    .select("*")
    .order("opened_at", { ascending: false })
    .limit(limit);

  if (runId) query = query.eq("run_id", parseInt(runId));
  if (status) query = query.eq("status", status);
  if (since) query = query.gte("opened_at", since);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fetch market questions for display
  const marketIds = [...new Set((data ?? []).map((t) => t.market_id))];
  let markets: Record<string, string> = {};
  if (marketIds.length > 0) {
    // Batch in chunks of 50
    for (let i = 0; i < marketIds.length; i += 50) {
      const chunk = marketIds.slice(i, i + 50);
      const { data: mData } = await supabase
        .from("markets")
        .select("id,question")
        .in("id", chunk);
      for (const m of mData ?? []) {
        markets[m.id] = m.question;
      }
    }
  }

  const enriched = (data ?? []).map((t) => ({
    ...t,
    market_question: markets[t.market_id] ?? t.market_id.slice(0, 12) + "...",
  }));

  return NextResponse.json(enriched);
}
