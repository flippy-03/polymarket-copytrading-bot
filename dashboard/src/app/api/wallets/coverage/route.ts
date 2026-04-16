import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/**
 * GET /api/wallets/coverage
 *
 * Returns enrichment coverage breakdown: totals, % enriched, counts by
 * strategy / confidence / archetype / rarity. Used by the /wallets header.
 */
export async function GET() {
  // Active wallets across both strategies (best-effort).
  let totalSpec = 0;
  let totalScalper = 0;
  try {
    const { data: sr } = await supabase
      .from("spec_ranking")
      .select("wallet", { count: "exact", head: false });
    totalSpec = new Set((sr ?? []).map((r) => r.wallet)).size;
  } catch {
    /* ignore */
  }
  try {
    const { data: sp } = await supabase
      .from("scalper_pool")
      .select("wallet_address")
      .is("exited_at", null);
    totalScalper = new Set((sp ?? []).map((r) => r.wallet_address)).size;
  } catch {
    /* ignore */
  }

  // Enriched profile aggregates.
  let profiles: {
    profile_confidence?: string | null;
    primary_archetype?: string | null;
    rarity_tier?: string | null;
    strategies_active?: string[] | null;
  }[] = [];
  try {
    const { data } = await supabase
      .from("wallet_profiles")
      .select("profile_confidence, primary_archetype, rarity_tier, strategies_active")
      .limit(5000);
    profiles = data ?? [];
  } catch {
    // wallet_profiles doesn't exist yet (pre-migration).
    return NextResponse.json({
      totals: {
        specialist: totalSpec,
        scalper: totalScalper,
        enriched: 0,
      },
      by_confidence: {},
      by_archetype: {},
      by_rarity: {},
      by_strategy_enriched: {},
      enrichment_ready: false,
    });
  }

  const by_confidence: Record<string, number> = {};
  const by_archetype: Record<string, number> = {};
  const by_rarity: Record<string, number> = {};
  const by_strategy_enriched: Record<string, number> = {
    SPECIALIST: 0,
    SCALPER: 0,
    BOTH: 0,
  };

  for (const p of profiles) {
    const c = p.profile_confidence || "LOW";
    by_confidence[c] = (by_confidence[c] || 0) + 1;
    const a = p.primary_archetype || "UNKNOWN";
    by_archetype[a] = (by_archetype[a] || 0) + 1;
    const r = p.rarity_tier || "COMMON";
    by_rarity[r] = (by_rarity[r] || 0) + 1;
    const strategies = Array.isArray(p.strategies_active) ? p.strategies_active : [];
    const hasS = strategies.includes("SPECIALIST");
    const hasC = strategies.includes("SCALPER");
    if (hasS && hasC) by_strategy_enriched.BOTH++;
    else if (hasS) by_strategy_enriched.SPECIALIST++;
    else if (hasC) by_strategy_enriched.SCALPER++;
  }

  return NextResponse.json({
    totals: {
      specialist: totalSpec,
      scalper: totalScalper,
      enriched: profiles.length,
    },
    by_confidence,
    by_archetype,
    by_rarity,
    by_strategy_enriched,
    enrichment_ready: true,
  });
}
