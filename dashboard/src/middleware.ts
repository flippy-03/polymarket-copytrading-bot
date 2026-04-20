import { NextResponse, type NextRequest } from "next/server";

/**
 * v3.1: force Cache-Control: no-store on every /api/* response.
 *
 * Without this, browsers (esp. Safari) happily cache JSON responses and
 * serve stale data on the next navigation or tab switch. Our dashboard
 * shows live trading state — caching it for even 30s means users see
 * yesterday's trades when yesterday's run was already closed.
 *
 * `export const dynamic = "force-dynamic"` in each route only affects
 * Next's own SSR/ISR cache; it does NOT control HTTP response headers.
 */
export function middleware(_request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Expires", "0");
  return response;
}

export const config = {
  matcher: "/api/:path*",
};
