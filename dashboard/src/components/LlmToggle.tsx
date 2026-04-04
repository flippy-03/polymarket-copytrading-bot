"use client";

import { useState, useEffect } from "react";

export default function LlmToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((d) => setEnabled(d.llm_enabled ?? true))
      .catch(() => setEnabled(true));
  }, []);

  const toggle = async () => {
    if (enabled === null) return;
    setLoading(true);
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm_enabled: !enabled }),
      });
      if (res.ok) {
        setEnabled(!enabled);
      }
    } catch {
      // ignore
    }
    setLoading(false);
  };

  if (enabled === null) return null;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-zinc-700 bg-zinc-800/50 px-4 py-2">
      <span className="text-sm text-zinc-400">LLM Filter</span>
      <button
        onClick={toggle}
        disabled={loading}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          enabled ? "bg-emerald-600" : "bg-zinc-600"
        } ${loading ? "opacity-50" : ""}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            enabled ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
      <span className={`text-xs font-medium ${enabled ? "text-emerald-400" : "text-zinc-500"}`}>
        {enabled ? "ON" : "OFF"}
      </span>
      {enabled && (
        <span className="text-xs text-zinc-500">Haiku 4.5</span>
      )}
    </div>
  );
}
