import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveStrategy } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

/**
 * GET /api/runs?strategy=BASKET|SCALPER
 *
 * Returns every run for the given strategy, newest first. The UI uses this to
 * populate the run selector in the sidebar: the ACTIVE row is what the user
 * sees by default, and picking a historical row lets them inspect what the
 * dashboards looked like during that checkpoint.
 */
export async function GET(request: Request) {
  const strategy = resolveStrategy(request);

  const { data, error } = await supabase
    .from("runs")
    .select("id, strategy, version, status, started_at, ended_at, notes, parent_run_id")
    .eq("strategy", strategy)
    .order("started_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
