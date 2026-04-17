import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const { data } = await supabase
    .from("roadmap_snapshots")
    .select("*")
    .order("snapshot_at", { ascending: false })
    .limit(1)
    .single();

  if (!data) {
    return NextResponse.json({ snapshot: null });
  }

  return NextResponse.json({ snapshot: data });
}
