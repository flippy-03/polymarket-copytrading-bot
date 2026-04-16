"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Strategy = "SPECIALIST" | "SCALPER";
export type ShadowMode = "REAL" | "SHADOW" | "BOTH";

const STRATEGY_KEY = "ct.strategy";
const RUN_KEY_PREFIX = "ct.run.";        // per-strategy: ct.run.BASKET, ct.run.SCALPER
const SHADOW_KEY = "ct.shadow";

type Ctx = {
  strategy: Strategy;
  setStrategy: (s: Strategy) => void;
  runId: string | null;                    // null = "follow ACTIVE"
  setRunId: (id: string | null) => void;
  shadowMode: ShadowMode;
  setShadowMode: (m: ShadowMode) => void;
};

const StrategyContext = createContext<Ctx | null>(null);

export function StrategyProvider({ children }: { children: React.ReactNode }) {
  const [strategy, setStrategyState] = useState<Strategy>("SPECIALIST");
  const [runId, setRunIdState] = useState<string | null>(null);
  const [shadowMode, setShadowModeState] = useState<ShadowMode>("REAL");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedStrategy = window.localStorage.getItem(STRATEGY_KEY);
    const initialStrategy: Strategy =
      savedStrategy === "SPECIALIST" || savedStrategy === "SCALPER" ? savedStrategy : "SPECIALIST";
    setStrategyState(initialStrategy);

    const savedRun = window.localStorage.getItem(RUN_KEY_PREFIX + initialStrategy);
    setRunIdState(savedRun && savedRun.length > 0 ? savedRun : null);

    const savedShadow = window.localStorage.getItem(SHADOW_KEY);
    if (savedShadow === "REAL" || savedShadow === "SHADOW" || savedShadow === "BOTH") {
      setShadowModeState(savedShadow);
    }
  }, []);

  const setStrategy = useCallback((s: Strategy) => {
    setStrategyState(s);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STRATEGY_KEY, s);
      const savedRun = window.localStorage.getItem(RUN_KEY_PREFIX + s);
      setRunIdState(savedRun && savedRun.length > 0 ? savedRun : null);
    }
  }, []);

  const setRunId = useCallback(
    (id: string | null) => {
      setRunIdState(id);
      if (typeof window !== "undefined") {
        if (id) window.localStorage.setItem(RUN_KEY_PREFIX + strategy, id);
        else window.localStorage.removeItem(RUN_KEY_PREFIX + strategy);
      }
    },
    [strategy],
  );

  const setShadowMode = useCallback((m: ShadowMode) => {
    setShadowModeState(m);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SHADOW_KEY, m);
    }
  }, []);

  return (
    <StrategyContext.Provider
      value={{ strategy, setStrategy, runId, setRunId, shadowMode, setShadowMode }}
    >
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategy(): Ctx {
  const ctx = useContext(StrategyContext);
  if (!ctx) {
    return {
      strategy: "SPECIALIST",
      setStrategy: () => {},
      runId: null,
      setRunId: () => {},
      shadowMode: "REAL",
      setShadowMode: () => {},
    };
  }
  return ctx;
}

/**
 * Build the query string fragment that every API call should append so the
 * server can filter to the current (strategy, run, shadow mode). `runId=null`
 * means "ACTIVE run for this strategy".
 */
export function ctxQueryString(
  strategy: Strategy,
  runId: string | null,
  shadowMode: ShadowMode,
): string {
  const p = new URLSearchParams();
  p.set("strategy", strategy);
  if (runId) p.set("run_id", runId);
  p.set("shadow", shadowMode);
  return p.toString();
}

export function strategyQueryParam(strategy: Strategy): string {
  return `strategy=${strategy}`;
}
