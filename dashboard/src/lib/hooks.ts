"use client";

import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Poll `fetcher` every `intervalMs` — but pause while the browser tab is
 * hidden (Page Visibility API). Resumes with an immediate fetch when the tab
 * becomes visible again.
 *
 * Defaults raised to 60 s to cut Supabase egress in half vs. the previous 30 s.
 * Pages that need fresher data (the dashboard home portfolio, positions, etc.)
 * can still override per call.
 */
export function useAutoRefresh<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 60000,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setLastUpdated(new Date());
    } catch (err) {
      console.error("Fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

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
        // Tab came back — fetch once immediately, then resume polling.
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
