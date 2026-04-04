import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/config — read bot configuration from portfolio_state.
 * POST /api/config — update bot configuration.
 *
 * Uses portfolio_state.metadata JSONB column to store config like llm_enabled.
 * If the metadata column doesn't exist yet, falls back to defaults.
 */

interface BotConfig {
  llm_enabled: boolean;
}

const DEFAULT_CONFIG: BotConfig = { llm_enabled: true };

export async function GET() {
  const { data } = await supabase
    .from("portfolio_state")
    .select("metadata")
    .order("run_id", { ascending: false })
    .limit(1);

  const metadata = data?.[0]?.metadata;
  const config: BotConfig = {
    llm_enabled: metadata?.llm_enabled ?? DEFAULT_CONFIG.llm_enabled,
  };

  return NextResponse.json(config);
}

export async function POST(request: Request) {
  const body = await request.json();
  const { llm_enabled } = body;

  if (typeof llm_enabled !== "boolean") {
    return NextResponse.json({ error: "llm_enabled must be a boolean" }, { status: 400 });
  }

  // Read current state
  const { data: current } = await supabase
    .from("portfolio_state")
    .select("id, metadata")
    .order("run_id", { ascending: false })
    .limit(1);

  if (!current?.[0]) {
    return NextResponse.json({ error: "No portfolio state found" }, { status: 404 });
  }

  const existing = current[0].metadata || {};
  const newMetadata = { ...existing, llm_enabled };

  const { error } = await supabase
    .from("portfolio_state")
    .update({ metadata: newMetadata })
    .eq("id", current[0].id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ llm_enabled, updated: true });
}
