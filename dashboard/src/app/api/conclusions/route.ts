import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

function classifyMarket(question: string): string {
  const q = (question || "").toLowerCase();
  // Crypto subcategories: daily vs weekly
  if (q.includes("bitcoin") || q.includes("btc")) {
    const isWeekly = /march 30|april|reach \$|dip to \$/.test(q) && !/on march 2[5-7]/.test(q);
    return isWeekly ? "CRYPTO_BTC_WEEKLY" : "CRYPTO_BTC_DAILY";
  }
  if (q.includes("ethereum") || q.includes("eth")) {
    const isWeekly = /march 30|april|reach \$|dip to \$/.test(q) && !/on march 2[5-7]/.test(q);
    return isWeekly ? "CRYPTO_ETH_WEEKLY" : "CRYPTO_ETH_DAILY";
  }
  if (/solana|dogecoin/.test(q)) return "CRYPTO_OTHER";
  if (/tweet|post \d|posts from/.test(q)) return "SOCIAL_COUNT";
  if (/elon|musk/.test(q)) return "SOCIAL_COUNT";
  if (/trump/.test(q)) return "POLITICS";
  if (/tariff/.test(q)) return "MACRO";
  if (/fed |rate cut|fomc|inflation|cpi/.test(q)) return "MACRO";
  if (/war|ukraine|ceasefire/.test(q)) return "GEOPOLITICS";
  if (/prime minister|president|election|governor|parliament/.test(q)) return "POLITICS";
  if (/spread:|win the|nba|nfl|nhl|mlb|tournament|championship/.test(q)) return "SPORTS";
  if (/release|album|movie|box office|kanye/.test(q)) return "ENTERTAINMENT";
  return "OTHER_EVENT";
}

function winRate(trades: any[]): number {
  if (trades.length === 0) return 0;
  return trades.filter((t) => (t.pnl_usd ?? 0) > 0).length / trades.length;
}
function totalPnl(trades: any[]): number {
  return trades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
}
function avg(arr: number[]): number {
  return arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
}
function round2(n: number): number { return Math.round(n * 100) / 100; }

export async function GET() {
  try {
    // === FETCH ALL DATA ===
    // Trades from all runs
    const [r1, r2, rNull] = await Promise.all([
      supabase.from("paper_trades").select("*").eq("run_id", 1).order("opened_at"),
      supabase.from("paper_trades").select("*").eq("run_id", 2).order("opened_at"),
      supabase.from("paper_trades").select("*").is("run_id", null).order("opened_at"),
    ]);

    const allTrades = [...(r1.data ?? []), ...(r2.data ?? []), ...(rNull.data ?? [])];
    const closedAll = allTrades.filter((t) => t.status === "CLOSED" && t.close_reason);
    const closedR2 = closedAll.filter((t) => t.run_id === 2);

    // Signals
    const { data: signals } = await supabase
      .from("signals")
      .select("id,market_id,status,total_score,divergence_score,momentum_score,smart_wallet_score,direction,confidence,price_at_signal,created_at")
      .limit(2000);

    // Shadow trades
    let shadows: any[] = [];
    try {
      const { data: sh } = await supabase.from("shadow_trades").select("*").limit(500);
      shadows = sh ?? [];
    } catch { /* table may not exist */ }

    // Get all market IDs
    const marketIds = new Set<string>();
    for (const t of allTrades) if (t.market_id) marketIds.add(t.market_id);
    for (const s of signals ?? []) if (s.market_id) marketIds.add(s.market_id);
    for (const sh of shadows) if (sh.market_id) marketIds.add(sh.market_id);

    // Fetch markets
    const { data: marketsData } = await supabase
      .from("markets")
      .select("id,question,category,yes_price,end_date,resolution")
      .in("id", Array.from(marketIds));

    const mktMap: Record<string, any> = {};
    for (const m of marketsData ?? []) mktMap[m.id] = m;
    const sigMap: Record<string, any> = {};
    for (const s of signals ?? []) sigMap[s.id] = s;

    // === ENRICH TRADES ===
    function enrichTrade(t: any) {
      const sig = sigMap[t.signal_id] ?? {};
      const mkt = mktMap[t.market_id] ?? {};
      t._score = sig.total_score;
      t._div = sig.divergence_score;
      t._mom = sig.momentum_score;
      t._sw = sig.smart_wallet_score;
      t._conf = sig.confidence;
      t._question = mkt.question ?? "";
      t._type = classifyMarket(mkt.question ?? "");
      t._resolution = mkt.resolution;
    }
    for (const t of closedAll) enrichTrade(t);

    // === SHADOW TRADE OUTCOMES ===
    const shadowOutcomes: any[] = [];
    for (const sh of shadows) {
      const sig = sigMap[sh.signal_id] ?? {};
      const mkt = mktMap[sh.market_id] ?? {};
      const entry = sh.entry_price ?? sig.price_at_signal;
      const direction = sh.direction ?? sig.direction;
      const resolution = mkt.resolution;
      const yesPrice = mkt.yes_price;

      if (!entry || !direction) continue;

      let finalYes: number;
      if (resolution === "YES") finalYes = 1.0;
      else if (resolution === "NO") finalYes = 0.0;
      else if (yesPrice != null) finalYes = yesPrice;
      else continue;

      const exitPrice = direction === "YES" ? finalYes : 1 - finalYes;
      const pnlPct = entry > 0 ? (exitPrice - entry) / entry : 0;

      shadowOutcomes.push({
        direction,
        entry: round2(entry),
        exit: round2(exitPrice),
        pnlPct: round2(pnlPct * 100),
        outcome: pnlPct > 0 ? "WIN" : "LOSS",
        score: sig.total_score,
        type: classifyMarket(mkt.question ?? ""),
        question: (mkt.question ?? "").slice(0, 100),
        blockedReason: sh.blocked_reason,
        resolved: resolution === "YES" || resolution === "NO",
      });
    }

    // === SNAPSHOT ANALYSIS: Did TS trades revert? ===
    const tsTrades = closedAll.filter((t) => t.close_reason === "TRAILING_STOP");
    const tsReversals: any[] = [];

    // Fetch post-close snapshots for TS trades (limit queries)
    for (const t of tsTrades.slice(0, 20)) {
      if (!t.market_id || !t.closed_at) continue;
      const { data: snaps } = await supabase
        .from("market_snapshots")
        .select("yes_price,snapshot_at")
        .eq("market_id", t.market_id)
        .gt("snapshot_at", t.closed_at)
        .order("snapshot_at")
        .limit(200);

      if (!snaps?.length) continue;

      const entry = t.entry_price ?? 0;
      let maxFav = 0, eventuallyWon = false;

      for (const snap of snaps) {
        const sp = snap.yes_price ?? 0.5;
        const move = t.direction === "YES"
          ? (sp - entry) / (entry || 1)
          : ((1 - sp) - (1 - entry)) / ((1 - entry) || 1);
        maxFav = Math.max(maxFav, move);
        if (move >= 0.50) eventuallyWon = true;
      }

      const mkt = mktMap[t.market_id] ?? {};
      if (mkt.resolution === (t.direction === "YES" ? "YES" : "NO")) eventuallyWon = true;

      tsReversals.push({
        direction: t.direction,
        entry: t.entry_price,
        exit: t.exit_price,
        pnl: round2(t.pnl_usd ?? 0),
        score: t._score,
        type: t._type,
        question: (t._question ?? "").slice(0, 80),
        maxFavorableAfter: round2(maxFav * 100),
        eventuallyWon,
        resolution: mkt.resolution,
      });
    }

    // === BUILD ANALYTICS ===
    const wins = closedAll.filter((t) => (t.pnl_usd ?? 0) > 0);
    const losses = closedAll.filter((t) => (t.pnl_usd ?? 0) <= 0);

    // Summary
    const summary = {
      total: closedAll.length,
      wins: wins.length,
      losses: losses.length,
      winRate: round2(winRate(closedAll) * 100),
      totalPnl: round2(totalPnl(closedAll)),
      avgWin: round2(avg(wins.map((t) => t.pnl_usd ?? 0))),
      avgLoss: round2(avg(losses.map((t) => t.pnl_usd ?? 0))),
      winLossRatio: losses.length > 0 && wins.length > 0
        ? round2(Math.abs(avg(wins.map((t) => t.pnl_usd)) / avg(losses.map((t) => t.pnl_usd))))
        : 0,
    };

    // By run
    const byRun = [1, 2].map((rid) => {
      const rt = closedAll.filter((t) => t.run_id === rid);
      return { run: rid, n: rt.length, winRate: Math.round(winRate(rt) * 100), pnl: round2(totalPnl(rt)) };
    });

    // By score bucket
    const scoreBuckets: Record<string, any[]> = { "65-70": [], "70-75": [], "75-80": [], "80+": [] };
    for (const t of closedAll) {
      const s = t._score;
      if (s == null) continue;
      if (s < 70) scoreBuckets["65-70"].push(t);
      else if (s < 75) scoreBuckets["70-75"].push(t);
      else if (s < 80) scoreBuckets["75-80"].push(t);
      else scoreBuckets["80+"].push(t);
    }
    const byScoreBucket = Object.entries(scoreBuckets).map(([bucket, ts]) => ({
      bucket, n: ts.length, winRate: Math.round(winRate(ts) * 100), pnl: round2(totalPnl(ts)),
    }));

    // By momentum
    const momBuckets: Record<string, any[]> = { "<30": [], "30-60": [], "60+": [] };
    for (const t of closedAll) {
      const s = t._mom;
      if (s == null) continue;
      if (s < 30) momBuckets["<30"].push(t);
      else if (s < 60) momBuckets["30-60"].push(t);
      else momBuckets["60+"].push(t);
    }
    const byMomentum = Object.entries(momBuckets).map(([bucket, ts]) => ({
      bucket, n: ts.length, winRate: Math.round(winRate(ts) * 100), pnl: round2(totalPnl(ts)),
    }));

    // By close reason
    const byReasonMap: Record<string, any[]> = {};
    for (const t of closedAll) {
      const r = t.close_reason ?? "UNKNOWN";
      if (!byReasonMap[r]) byReasonMap[r] = [];
      byReasonMap[r].push(t);
    }
    const byCloseReason = Object.entries(byReasonMap).map(([reason, ts]) => {
      const durations = ts
        .filter((t) => t.opened_at && t.closed_at)
        .map((t) => (new Date(t.closed_at).getTime() - new Date(t.opened_at).getTime()) / 3600000);
      return {
        reason, n: ts.length, winRate: Math.round(winRate(ts) * 100),
        pnl: round2(totalPnl(ts)), avgHoldHours: round2(avg(durations)),
      };
    }).sort((a, b) => b.n - a.n);

    // By direction
    const yesTrades = closedAll.filter((t) => t.direction === "YES");
    const noTrades = closedAll.filter((t) => t.direction === "NO");
    const byDirection = {
      YES: { n: yesTrades.length, winRate: Math.round(winRate(yesTrades) * 100), pnl: round2(totalPnl(yesTrades)) },
      NO: { n: noTrades.length, winRate: Math.round(winRate(noTrades) * 100), pnl: round2(totalPnl(noTrades)) },
    };

    // By market type (granular)
    const typeMap: Record<string, any[]> = {};
    for (const t of closedAll) {
      if (!typeMap[t._type]) typeMap[t._type] = [];
      typeMap[t._type].push(t);
    }
    const byMarketType = Object.entries(typeMap)
      .map(([type, ts]) => ({
        type, n: ts.length, winRate: Math.round(winRate(ts) * 100), pnl: round2(totalPnl(ts)),
      }))
      .sort((a, b) => b.n - a.n);

    // By entry price range
    const priceRanges: Record<string, any[]> = {
      "0.05-0.10": [], "0.10-0.20": [], "0.20-0.35": [],
      "0.35-0.50": [], "0.50-0.65": [], "0.65-0.80": [],
    };
    for (const t of closedAll) {
      const ep = t.entry_price ?? 0;
      if (ep < 0.10) priceRanges["0.05-0.10"].push(t);
      else if (ep < 0.20) priceRanges["0.10-0.20"].push(t);
      else if (ep < 0.35) priceRanges["0.20-0.35"].push(t);
      else if (ep < 0.50) priceRanges["0.35-0.50"].push(t);
      else if (ep < 0.65) priceRanges["0.50-0.65"].push(t);
      else priceRanges["0.65-0.80"].push(t);
    }
    const byEntryPrice = Object.entries(priceRanges).map(([range, ts]) => ({
      range, n: ts.length, winRate: ts.length > 0 ? Math.round(winRate(ts) * 100) : 0,
      pnl: round2(totalPnl(ts)),
    }));

    // Heatmap: Score + Direction + Momentum combos
    const combos: Record<string, { n: number; wins: number; pnl: number }> = {};
    for (const t of closedAll) {
      const sc = (t._score ?? 0) >= 80 ? "80+" : (t._score ?? 0) >= 75 ? "75-80" : "<75";
      const mom = (t._mom ?? 0) >= 60 ? "mom60+" : "mom<60";
      const dir = t.direction;
      const key = `${sc} / ${dir} / ${mom}`;
      if (!combos[key]) combos[key] = { n: 0, wins: 0, pnl: 0 };
      combos[key].n++;
      if ((t.pnl_usd ?? 0) > 0) combos[key].wins++;
      combos[key].pnl += t.pnl_usd ?? 0;
    }
    const heatmap = Object.entries(combos).map(([key, v]) => ({
      combo: key,
      n: v.n,
      winRate: v.n > 0 ? Math.round(v.wins / v.n * 100) : 0,
      pnl: round2(v.pnl),
    })).sort((a, b) => b.pnl - a.pnl);

    // Signal stats
    const allSignals = signals ?? [];
    const executed = allSignals.filter((s) => s.status === "EXECUTED");
    const expired = allSignals.filter((s) => s.status === "EXPIRED");
    const signalStats = {
      total: allSignals.length,
      executed: executed.length,
      expired: expired.length,
      executionRate: allSignals.length > 0 ? Math.round(executed.length / allSignals.length * 100) : 0,
      avgScoreExecuted: round2(avg(executed.map((s) => s.total_score ?? 0))),
      avgScoreExpired: round2(avg(expired.map((s) => s.total_score ?? 0))),
    };

    // TS detail
    const tsDetail = (byReasonMap["TRAILING_STOP"] ?? []).map((t) => ({
      direction: t.direction, entry: t.entry_price, exit: t.exit_price,
      pnl: round2(t.pnl_usd ?? 0), score: t._score, question: (t._question ?? "").slice(0, 80), type: t._type,
    }));

    // Shadow summary
    const resolvedShadows = shadowOutcomes.filter((s) => s.resolved);
    const shadowWins = resolvedShadows.filter((s) => s.outcome === "WIN");
    const shadowSummary = {
      total: shadows.length,
      withOutcome: shadowOutcomes.length,
      resolved: resolvedShadows.length,
      resolvedWR: resolvedShadows.length > 0 ? Math.round(shadowWins.length / resolvedShadows.length * 100) : 0,
      outcomes: shadowOutcomes.slice(0, 50),
    };

    // TS reversal summary
    const tsReversed = tsReversals.filter((r) => r.eventuallyWon);
    const tsReversalSummary = {
      analyzed: tsReversals.length,
      eventuallyWon: tsReversed.length,
      wouldHaveWonPct: tsReversals.length > 0 ? Math.round(tsReversed.length / tsReversals.length * 100) : 0,
      details: tsReversals,
    };

    // Trade list
    const tradeList = closedAll.map((t) => ({
      runId: t.run_id, direction: t.direction, score: t._score, confidence: t._conf,
      entry: t.entry_price, exit: t.exit_price, pnl: round2(t.pnl_usd ?? 0),
      pnlPct: round2((t.pnl_pct ?? 0) * 100), closeReason: t.close_reason,
      question: (t._question ?? "").slice(0, 100), type: t._type,
      openedAt: t.opened_at, closedAt: t.closed_at,
    }));

    // Equity curve
    let cumPnl = 0;
    const equityCurve = closedAll.map((t, i) => {
      cumPnl += t.pnl_usd ?? 0;
      return { trade: i + 1, pnl: round2(cumPnl), tradePnl: round2(t.pnl_usd ?? 0), reason: t.close_reason };
    });

    return NextResponse.json({
      summary, byRun, byScoreBucket, byMomentum, byCloseReason, byDirection,
      byMarketType, byEntryPrice, heatmap, signalStats, tsDetail,
      shadowSummary, tsReversalSummary, tradeList, equityCurve,
    });
  } catch (err: any) {
    console.error("Conclusions API error:", err);
    return NextResponse.json({ error: err.message ?? "Database unavailable" }, { status: 500 });
  }
}
