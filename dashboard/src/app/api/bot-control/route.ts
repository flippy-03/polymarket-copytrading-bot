import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import {
  resolveStrategy,
  resolveRunId,
} from "@/lib/strategy-param";

export const dynamic = "force-dynamic";

/** GET — return current pause state for the real portfolio of a strategy. */
export async function GET(request: Request) {
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  if (!runId) {
    return NextResponse.json({ error: "No active run" }, { status: 404 });
  }

  const { data, error } = await supabase
    .from("portfolio_state_ct")
    .select("is_circuit_broken, requires_manual_review, circuit_broken_until, consecutive_losses")
    .eq("strategy", strategy)
    .eq("run_id", runId)
    .eq("is_shadow", false)
    .limit(1);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const row = data?.[0];
  return NextResponse.json({
    is_paused: row?.is_circuit_broken ?? false,
    requires_manual_review: row?.requires_manual_review ?? false,
    circuit_broken_until: row?.circuit_broken_until ?? null,
    consecutive_losses: row?.consecutive_losses ?? 0,
  });
}

/**
 * POST — pause or resume the bot manually.
 * Body: { action: "pause" | "resume" }
 *
 * pause  → is_circuit_broken=true, requires_manual_review=true (no timer)
 * resume → clears all flags and resets consecutive_losses to 0
 */
export async function POST(request: Request) {
  const strategy = resolveStrategy(request);
  const runId = await resolveRunId(request, strategy);

  if (!runId) {
    return NextResponse.json({ error: "No active run" }, { status: 404 });
  }

  let body: { action?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const action = body.action;
  if (action !== "pause" && action !== "resume") {
    return NextResponse.json(
      { error: 'action must be "pause" or "resume"' },
      { status: 400 },
    );
  }

  const patch =
    action === "pause"
      ? {
          is_circuit_broken: true,
          circuit_broken_until: null,
          requires_manual_review: true,
        }
      : {
          is_circuit_broken: false,
          circuit_broken_until: null,
          requires_manual_review: false,
          consecutive_losses: 0,
        };

  const { error } = await supabase
    .from("portfolio_state_ct")
    .update(patch)
    .eq("strategy", strategy)
    .eq("run_id", runId)
    .eq("is_shadow", false);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ success: true, action, strategy, run_id: runId });
}
