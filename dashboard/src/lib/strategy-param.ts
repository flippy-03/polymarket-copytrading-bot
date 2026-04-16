import { supabase } from "@/lib/supabase";

export type Strategy = "SPECIALIST" | "SCALPER";
export type ShadowMode = "REAL" | "SHADOW" | "BOTH";

export function resolveStrategy(request: Request): Strategy {
  const { searchParams } = new URL(request.url);
  const raw = (searchParams.get("strategy") || "").toUpperCase();
  return raw === "SCALPER" ? "SCALPER" : "SPECIALIST";
}

export function resolveShadowMode(request: Request): ShadowMode {
  const { searchParams } = new URL(request.url);
  const raw = (searchParams.get("shadow") || "").toUpperCase();
  if (raw === "SHADOW") return "SHADOW";
  if (raw === "BOTH") return "BOTH";
  return "REAL";
}

/**
 * Resolve the run_id to filter by.
 * - If the client passed ?run_id=<uuid>, use it verbatim.
 * - Otherwise return the ACTIVE run for the given strategy.
 * - Returns null only if the strategy has no runs at all (pre-migration state).
 */
export async function resolveRunId(
  request: Request,
  strategy: Strategy,
): Promise<string | null> {
  const { searchParams } = new URL(request.url);
  const explicit = searchParams.get("run_id");
  if (explicit && explicit.length > 0) return explicit;

  const { data, error } = await supabase
    .from("runs")
    .select("id")
    .eq("strategy", strategy)
    .eq("status", "ACTIVE")
    .limit(1);

  if (error || !data || data.length === 0) return null;
  return data[0].id as string;
}

/**
 * Translate the shadow-mode query param into the concrete `is_shadow` filter
 * applied to a Supabase query. Returns:
 *   - boolean  — exact match (REAL → false, SHADOW → true)
 *   - null     — no filter (BOTH)
 */
export function isShadowFilter(mode: ShadowMode): boolean | null {
  if (mode === "REAL") return false;
  if (mode === "SHADOW") return true;
  return null;
}
