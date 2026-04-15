import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

// Contrarian-era research view has been retired. Keep a no-op endpoint so
// any lingering fetch calls don't 404.
export async function GET() {
  return NextResponse.json({ retired: true });
}
