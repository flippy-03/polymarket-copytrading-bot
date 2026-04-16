import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  isShadowFilter,
  resolveRunId,
  resolveShadowMode,
  resolveStrategy,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

const CLOB_API = "https://clob.polymarket.com";

const POSITION_COLUMNS =
  "id,strategy,run_id,source_wallet,market_polymarket_id,market_question," +
  "direction,outcome_token_id,entry_price,position_usd,opened_at,is_shadow,metadata";

/** Fetch the current mid-price for a single outcome token from Polymarket CLOB. */
async function fetchClobPrice(tokenId: string): Promise<number | null> {
  try {
    const resp = await fetch(
      `${CLOB_API}/price?token_id=${encodeURIComponent(tokenId)}&side=BUY`,
      { cache: "no-store" },
    );
    if (!resp.ok) return null;
    const json = (await resp.json()) as { price?: string | number };
    const p = Number(json.price ?? 0);
    return p > 0 ? p : null;
  } catch {
    return null;
  }
}

export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const shadowMode = resolveShadowMode(request);
  const runId = await resolveRunId(request, strategy);

  let query = supabase
    .from("copy_trades")
    .select(POSITION_COLUMNS)
    .eq("status", "OPEN")
    .eq("strategy", strategy)
    .order("opened_at", { ascending: false });

  if (runId) query = query.eq("run_id", runId);

  const isShadow = isShadowFilter(shadowMode);
  if (isShadow !== null) query = query.eq("is_shadow", isShadow);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Cast: interpolated column-list select defeats supabase-js row-type inference.
  const rows = ((data ?? []) as unknown) as Array<Record<string, unknown>>;

  // Fetch current prices from Polymarket CLOB for all unique tokens in parallel.
  // With ≤7 open positions this adds ~200-500 ms latency but gives real-time P&L.
  const uniqueTokenIds = [
    ...new Set(
      rows
        .map((r) => String(r.outcome_token_id ?? ""))
        .filter(Boolean),
    ),
  ];

  const priceMap: Record<string, number> = {};
  if (uniqueTokenIds.length > 0) {
    const entries = await Promise.all(
      uniqueTokenIds.map(async (tid) => [tid, await fetchClobPrice(tid)] as const),
    );
    for (const [tid, price] of entries) {
      if (price != null) priceMap[tid] = price;
    }
  }

  const enriched = rows.map((t) => {
    const entry = Number(t.entry_price ?? 0);
    const tokenId = String(t.outcome_token_id ?? "");
    const current = priceMap[tokenId] ?? entry;  // fall back to entry if CLOB unavailable
    const shares = entry > 0 ? Number(t.position_usd ?? 0) / entry : 0;
    const unrealized_pnl = Math.round(shares * (current - entry) * 100) / 100;
    const unrealized_pnl_pct = entry > 0 ? (current - entry) / entry : 0;
    return {
      ...t,
      market_question:
        t.market_question ??
        `${String(t.market_polymarket_id ?? "").slice(0, 12)}…`,
      current_price: current,
      unrealized_pnl,
      unrealized_pnl_pct: Math.round(unrealized_pnl_pct * 10000) / 10000,
    };
  });

  return NextResponse.json(enriched);
}
