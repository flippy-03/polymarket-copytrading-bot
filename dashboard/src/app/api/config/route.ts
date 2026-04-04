import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/config — read bot configuration from portfolio_state.
 * POST /api/config — update bot configuration.
 *
 * Uses portfolio_state.metadata JSONB column to store config.
 * Supported fields: llm_enabled, llm_api_key, llm_model, llm_provider
 */

interface BotConfig {
  llm_enabled: boolean;
  llm_api_key: string;
  llm_model: string;
  llm_provider: string;
}

const DEFAULT_CONFIG: BotConfig = {
  llm_enabled: false,
  llm_api_key: "",
  llm_model: "claude-haiku-4-5-20251001",
  llm_provider: "anthropic",
};

export async function GET() {
  const { data } = await supabase
    .from("portfolio_state")
    .select("metadata")
    .order("run_id", { ascending: false })
    .limit(1);

  const metadata = data?.[0]?.metadata ?? {};
  const config: BotConfig = {
    llm_enabled: metadata.llm_enabled ?? DEFAULT_CONFIG.llm_enabled,
    llm_api_key: metadata.llm_api_key ?? DEFAULT_CONFIG.llm_api_key,
    llm_model: metadata.llm_model ?? DEFAULT_CONFIG.llm_model,
    llm_provider: metadata.llm_provider ?? DEFAULT_CONFIG.llm_provider,
  };

  return NextResponse.json(config);
}

export async function POST(request: Request) {
  const body = await request.json();

  const allowed = ["llm_enabled", "llm_api_key", "llm_model", "llm_provider"] as const;
  const update: Partial<BotConfig> = {};
  for (const key of allowed) {
    if (key in body) update[key] = body[key] as never;
  }

  if (Object.keys(update).length === 0) {
    return NextResponse.json({ error: "No valid fields to update" }, { status: 400 });
  }

  const { data: current } = await supabase
    .from("portfolio_state")
    .select("id, metadata")
    .order("run_id", { ascending: false })
    .limit(1);

  if (!current?.[0]) {
    return NextResponse.json({ error: "No portfolio state found" }, { status: 404 });
  }

  const existing = current[0].metadata || {};
  const newMetadata = { ...existing, ...update };

  const { error } = await supabase
    .from("portfolio_state")
    .update({ metadata: newMetadata })
    .eq("id", current[0].id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ updated: true, ...update });
}
