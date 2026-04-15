"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Strategy = "BASKET" | "SCALPER";
const STORAGE_KEY = "ct.strategy";

type Ctx = {
  strategy: Strategy;
  setStrategy: (s: Strategy) => void;
};

const StrategyContext = createContext<Ctx | null>(null);

export function StrategyProvider({ children }: { children: React.ReactNode }) {
  const [strategy, setStrategyState] = useState<Strategy>("BASKET");

  useEffect(() => {
    const saved = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;
    if (saved === "BASKET" || saved === "SCALPER") {
      setStrategyState(saved);
    }
  }, []);

  const setStrategy = useCallback((s: Strategy) => {
    setStrategyState(s);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, s);
    }
  }, []);

  return (
    <StrategyContext.Provider value={{ strategy, setStrategy }}>
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategy(): Ctx {
  const ctx = useContext(StrategyContext);
  if (!ctx) {
    // Safe fallback so server-rendered components don't crash outside of the provider.
    return { strategy: "BASKET", setStrategy: () => {} };
  }
  return ctx;
}

export function strategyQueryParam(strategy: Strategy): string {
  return `strategy=${strategy}`;
}
