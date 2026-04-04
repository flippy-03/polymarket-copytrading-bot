import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("run_id");

  let query = supabase
    .from("portfolio_state")
    .select("*")
    .order("run_id", { ascending: false })
    .limit(1);

  if (runId) {
    query = supabase
      .from("portfolio_state")
      .select("*")
      .eq("run_id", parseInt(runId))
      .limit(1);
  }

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data?.[0] ?? null);
}
