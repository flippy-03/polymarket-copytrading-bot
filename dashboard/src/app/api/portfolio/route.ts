import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);

  let query = supabase
    .from("portfolio_state_ct")
    .select("*")
    .eq("strategy", strategy);

  if (runId) query = query.eq("run_id", runId);

  const isShadow = isShadowFilter(shadowMode);

  if (isShadow === null) {
    // BOTH → return { real, shadow } on a single envelope so the UI can decide.
    const { data, error } = await query;
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    const real = (data ?? []).find((r) => r.is_shadow === false) ?? null;
    const shadow = (data ?? []).find((r) => r.is_shadow === true) ?? null;
    return NextResponse.json({ real, shadow, both: true, run_id: runId });
  }

  query = query.eq("is_shadow", isShadow);
  const { data, error } = await query.limit(1);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data?.[0] ?? null);
}
