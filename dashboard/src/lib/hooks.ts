"use client";

import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Module-level cache keyed by `cacheKey`. Persists across unmounts of a
 * single browser session so switching strategies shows last-known data
 * instantly while the new fetch completes in background.
 */
const refreshCache = new Map<string, unknown>();

/**
 * Populate the auto-refresh cache without mounting a component. Used by the
 * home page to warm up the other strategy's data right after initial load,
 * so the first strategy switch happens instantly instead of waiting for the
 * first fetch.
 *
 * Cache keys must match those used by `useAutoRefresh(fetcher, interval, cacheKey)`.
 */
export function prefetchIntoCache<T>(cacheKey: string, fetcher: () => Promise<T>): void {
  if (refreshCache.has(cacheKey)) return; // already warm
  fetcher()
    .then((result) => {
      refreshCache.set(cacheKey, result);
    })
    .catch(() => {
      // Swallow — the next real mount of useAutoRefresh will retry.
    });
}

/**
 * Poll `fetcher` every `intervalMs` — but pause while the browser tab is
 * hidden (Page Visibility API). Resumes with an immediate fetch when the tab
 * becomes visible again.
 *
 * If `cacheKey` is provided, the last successful response is kept in memory
 * and surfaced immediately when the hook re-mounts or when `cacheKey` changes
 * (e.g. user switches strategy). The background refetch still runs.
 */
export function useAutoRefresh<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 60000,
  cacheKey?: string,
) {
  const initial = cacheKey ? (refreshCache.get(cacheKey) as T | undefined) ?? null : null;
  const [data, setData] = useState<T | null>(initial);
  const [loading, setLoading] = useState(initial === null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const cacheKeyRef = useRef(cacheKey);
  cacheKeyRef.current = cacheKey;

  const refresh = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setLastUpdated(new Date());
      const key = cacheKeyRef.current;
      if (key) refreshCache.set(key, result);
    } catch (err) {
      console.error("Fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // When the cacheKey changes (user switches strategy/runId), hydrate `data`
  // with the cached value for the new key — keeps the UI responsive while
  // the background refetch fires.
  useEffect(() => {
    if (!cacheKey) return;
    const cached = refreshCache.get(cacheKey) as T | undefined;
    if (cached !== undefined) {
      setData(cached);
      setLoading(false);
    }
  }, [cacheKey]);

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (id !== null) return;
      id = setInterval(refresh, intervalMs);
    };
    const stop = () => {
      if (id === null) return;
      clearInterval(id);
      id = null;
    };

    const onVisibilityChange = () => {
      if (typeof document === "undefined") return;
      if (document.hidden) {
        stop();
      } else {
        refresh();
        start();
      }
    };

    refresh();
    if (typeof document !== "undefined" && !document.hidden) {
      start();
    }
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    return () => {
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
  }, [refresh, intervalMs]);

  return { data, loading, lastUpdated, refresh };
}

export function formatPnl(value: number | null | undefined): string {
  const v = value ?? 0;
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

export function formatPct(value: number | null | undefined): string {
  const v = value ?? 0;
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

export function pnlColor(value: number | null | undefined): string {
  const v = value ?? 0;
  if (v > 0) return "var(--green)";
  if (v < 0) return "var(--red)";
  return "var(--text-secondary)";
}

export function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h`;
  const mins = Math.floor(diff / (1000 * 60));
  return `${mins}m`;
}

/**
 * Format an ISO timestamp as "HH:MMh" in Europe/Madrid time.
 * Renders the same string server-side and client-side regardless of the
 * viewer's browser locale (uses Intl with a fixed timeZone).
 */
export function formatClosesAt(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "—";
    const hm = new Intl.DateTimeFormat("es-ES", {
      timeZone: "Europe/Madrid",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(d);
    return `${hm}h`;
  } catch {
    return "—";
  }
}

/**
 * Expected Value on a $1 stake: EV = P(win) − price.
 *
 * `avgHitRate` is the SPECIALIST bot's estimator of P(win) — mean historical
 * hit rate of the specialists that generated the signal. EV > 0 means the
 * trade is favoured vs. the market's implied probability (= entry price).
 *
 * Returns a number in [-1, 1] (fraction of $1 staked), or null if inputs missing.
 */
export function computeEV(
  avgHitRate: number | null | undefined,
  entryPrice: number | null | undefined,
): number | null {
  if (avgHitRate == null || entryPrice == null) return null;
  const hr = Number(avgHitRate);
  const ep = Number(entryPrice);
  if (!isFinite(hr) || !isFinite(ep) || ep <= 0 || ep >= 1) return null;
  return hr - ep;
}

import type { TimeFilter } from "@/lib/types";

export function getDateFromFilter(filter: TimeFilter): string | null {
  if (filter === "all") return null;
  const now = new Date();
  switch (filter) {
    case "today":
      return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
    case "1w":
      return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString();
    case "1m":
      return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString();
    case "3m":
      return new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000).toISOString();
    case "1y":
      return new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000).toISOString();
    default:
      return null;
  }
}
