import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

// Placeholder — config endpoint kept to satisfy any remaining callers.
// Copytrading strategies are configured via src/strategies/common/config.py / env vars.
export async function GET() {
  return NextResponse.json({
    paper_mode: true,
    strategies: ["BASKET", "SCALPER"],
  });
}
