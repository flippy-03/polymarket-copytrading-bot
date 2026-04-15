import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

// Hard ceiling: the home page equity curve only needs recent trades, and the
// Recent Trades table is capped at 50. Anything above this is waste.
const MAX_LIMIT = 200;

// Columns actually consumed by the dashboard (page.tsx + analytics).
// select("*") previously pulled shares, metadata, is_shadow, etc. unused client-side.
const TRADE_COLUMNS =
  "id,strategy,run_id,source_wallet,market_polymarket_id,market_question," +
  "market_category,direction,outcome_token_id,entry_price,exit_price," +
  "position_usd,pnl_usd,pnl_pct,status,close_reason,opened_at,closed_at,is_shadow";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);
  const status = searchParams.get("status"); // OPEN, CLOSED, or null (all)
  const since = searchParams.get("since");
  const requested = parseInt(searchParams.get("limit") ?? "100");
  const limit = Math.min(
    Number.isFinite(requested) && requested > 0 ? requested : 100,
    MAX_LIMIT,
  );

  let query = supabase
    .from("copy_trades")
    .select(TRADE_COLUMNS)
    .eq("strategy", strategy)
    .order("opened_at", { ascending: false })
    .limit(limit);

  if (runId) query = query.eq("run_id", runId);
  const isShadow = isShadowFilter(shadowMode);
  if (isShadow !== null) query = query.eq("is_shadow", isShadow);
  if (status) query = query.eq("status", status);
  if (since) query = query.gte("opened_at", since);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Cast: interpolated column-list select defeats supabase-js row-type inference.
  const rows = ((data ?? []) as unknown) as Array<Record<string, unknown>>;
  const enriched = rows.map((t) => ({
    ...t,
    market_question:
      t.market_question ?? `${String(t.market_polymarket_id ?? "").slice(0, 12)}…`,
  }));

  return NextResponse.json(enriched);
}
