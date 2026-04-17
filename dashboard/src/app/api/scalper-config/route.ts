import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { resolveRunId } from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

const DEFAULTS: Record<string, unknown> = {
  min_hit_rate: 0.55,
  min_trade_count: 8,
  trade_pct: 0.15,
  max_trade_pct: 0.25,
  max_drawdown_pct: 0.30,
  health_check_hours: 72,
  cooldown_days_base: 30,
  global_loss_limit: 6,
  priority_market_types: [],
};

export async function GET(request: Request) {
  const runId = await resolveRunId(request, "SCALPER");
  if (!runId) return NextResponse.json({ config: DEFAULTS });

  const { data } = await supabase
    .from("scalper_config")
    .select("config, updated_at")
    .eq("run_id", runId)
    .limit(1)
    .single();

  return NextResponse.json({
    config: { ...DEFAULTS, ...(data?.config ?? {}) },
    updated_at: data?.updated_at ?? null,
  });
}

export async function PUT(request: Request) {
  const runId = await resolveRunId(request, "SCALPER");
  if (!runId) {
    return NextResponse.json({ error: "no active SCALPER run" }, { status: 400 });
  }

  const body = await request.json();
  const config = body.config;
  if (!config || typeof config !== "object") {
    return NextResponse.json({ error: "config object required" }, { status: 400 });
  }

  const { error } = await supabase
    .from("scalper_config")
    .upsert(
      { run_id: runId, config, updated_at: new Date().toISOString() },
      { onConflict: "run_id" }
    );

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
