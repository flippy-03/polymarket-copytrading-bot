import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const { data, error } = await supabase
    .from("spec_market_type_rankings")
    .select("market_type,n_specialists,avg_hit_rate,top_hit_rate,total_trades,priority_score,last_updated_ts")
    .order("priority_score", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
