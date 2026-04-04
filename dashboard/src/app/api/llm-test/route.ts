import { NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

/**
 * POST /api/llm-test — test LLM API connection with a given API key and model.
 * Returns { ok: true, model, latency_ms } or { ok: false, error }.
 */
export async function POST(request: Request) {
  const body = await request.json();
  const { api_key, model = "claude-haiku-4-5-20251001" } = body;

  if (!api_key || typeof api_key !== "string") {
    return NextResponse.json({ ok: false, error: "api_key is required" }, { status: 400 });
  }

  const start = Date.now();
  try {
    const client = new Anthropic({ apiKey: api_key });
    await client.messages.create({
      model,
      max_tokens: 8,
      messages: [{ role: "user", content: "Reply with: ok" }],
    });
    return NextResponse.json({ ok: true, model, latency_ms: Date.now() - start });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: msg }, { status: 200 });
  }
}
