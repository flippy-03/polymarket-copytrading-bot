import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Columns consumed by dashboard/src/app/page.tsx + types.ts PortfolioState.
const PORTFOLIO_COLUMNS =
  "strategy,run_id,is_shadow,initial_capital,current_capital,peak_capital," +
  "total_pnl,total_pnl_pct,total_trades,winning_trades,losing_trades,win_rate," +
  "max_drawdown,consecutive_losses,is_circuit_broken,circuit_broken_until," +
  "requires_manual_review,open_positions,max_open_positions,updated_at";

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);

  let query = supabase
    .from("portfolio_state_ct")
    .select(PORTFOLIO_COLUMNS)
    .eq("strategy", strategy);

  if (runId) query = query.eq("run_id", runId);

  const isShadow = isShadowFilter(shadowMode);

  if (isShadow === null) {
    // BOTH → return { real, shadow } on a single envelope so the UI can decide.
    const { data, error } = await query;
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    // Cast: with an interpolated column-list select string, supabase-js can't
    // infer the row shape — we know it's portfolio_state_ct rows.
    const rows = ((data ?? []) as unknown) as Array<Record<string, unknown>>;
    const real = rows.find((r) => r.is_shadow === false) ?? null;
    const shadow = rows.find((r) => r.is_shadow === true) ?? null;
    return NextResponse.json({ real, shadow, both: true, run_id: runId });
  }

  query = query.eq("is_shadow", isShadow);
  const { data, error } = await query.limit(1);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data?.[0] ?? null);
}
