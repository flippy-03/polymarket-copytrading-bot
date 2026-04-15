import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);

  const { data, error } = await supabase
    .from("portfolio_state_ct")
    .select("*")
    .eq("strategy", strategy)
    .limit(1);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data?.[0] ?? null);
}
