import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

// Returns each active basket with its members and recent consensus signals.
export async function GET() {
  const { data: baskets, error: basketErr } = await supabase
    .from("baskets")
    .select("id, category, status, consensus_threshold, time_window_hours, max_capital_pct, created_at, updated_at")
    .eq("status", "ACTIVE")
    .order("category");

  if (basketErr) {
    return NextResponse.json({ error: basketErr.message }, { status: 500 });
  }

  const basketIds = (baskets ?? []).map((b) => b.id as string);

  const [{ data: members }, { data: signals }] = await Promise.all([
    supabase
      .from("basket_wallets")
      .select("basket_id, wallet_address, rank_score, rank_position, entered_at")
      .is("exited_at", null)
      .in("basket_id", basketIds.length ? basketIds : ["__none__"]),
    supabase
      .from("consensus_signals")
      .select(
        "id, basket_id, market_polymarket_id, market_question, direction, consensus_pct, wallets_agreeing, wallets_total, status, price_at_signal, created_at, executed_at",
      )
      .in("basket_id", basketIds.length ? basketIds : ["__none__"])
      .order("created_at", { ascending: false })
      .limit(200),
  ]);

  const membersByBasket = new Map<string, typeof members>();
  for (const m of members ?? []) {
    const id = m.basket_id as string;
    if (!membersByBasket.has(id)) membersByBasket.set(id, []);
    membersByBasket.get(id)!.push(m);
  }

  const signalsByBasket = new Map<string, typeof signals>();
  for (const s of signals ?? []) {
    const id = s.basket_id as string;
    if (!signalsByBasket.has(id)) signalsByBasket.set(id, []);
    signalsByBasket.get(id)!.push(s);
  }

  const out = (baskets ?? []).map((b) => {
    const id = b.id as string;
    const ms = (membersByBasket.get(id) ?? []).slice().sort(
      (a, b) => (a.rank_position ?? 99) - (b.rank_position ?? 99),
    );
    const ss = signalsByBasket.get(id) ?? [];
    return {
      ...b,
      members: ms,
      member_count: ms.length,
      signals: ss,
      pending_signals: ss.filter((s) => s.status === "PENDING").length,
    };
  });

  return NextResponse.json(out);
}
