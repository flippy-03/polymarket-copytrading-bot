"use client";

import { useEffect, useState } from "react";

const ANTHROPIC_MODELS = [
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5 — fast & cheap (recommended)" },
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6 — balanced" },
  { id: "claude-opus-4-6", label: "Opus 4.6 — most capable" },
];

interface Config {
  llm_enabled: boolean;
  llm_api_key: string;
  llm_model: string;
  llm_provider: string;
}

type TestState = "idle" | "loading" | "ok" | "error";

export default function SettingsPage() {
  const [config, setConfig] = useState<Config | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("claude-haiku-4-5-20251001");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testState, setTestState] = useState<TestState>("idle");
  const [testMsg, setTestMsg] = useState("");

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((d: Config) => {
        setConfig(d);
        setApiKey(d.llm_api_key ?? "");
        setModel(d.llm_model ?? "claude-haiku-4-5-20251001");
      });
  }, []);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ llm_api_key: apiKey, llm_model: model, llm_provider: "anthropic" }),
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const testConnection = async () => {
    if (!apiKey) return;
    setTestState("loading");
    setTestMsg("");
    try {
      const res = await fetch("/api/llm-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey, model }),
      });
      const data = await res.json();
      if (data.ok) {
        setTestState("ok");
        setTestMsg(`Connected — ${data.latency_ms}ms`);
      } else {
        setTestState("error");
        setTestMsg(data.error || "Unknown error");
      }
    } catch {
      setTestState("error");
      setTestMsg("Request failed");
    }
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center h-64 text-zinc-500 text-sm">
        Loading...
      </div>
    );
  }

  return (
    <div className="max-w-xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-zinc-400 mt-1">Bot configuration and integrations</p>
      </div>

      {/* LLM Section */}
      <section className="rounded-xl border border-zinc-700 bg-zinc-800/50 p-6 space-y-5">
        <div>
          <h2 className="text-base font-semibold text-white">LLM Filter</h2>
          <p className="text-xs text-zinc-400 mt-1">
            Claude validates each trade signal before execution. Enable the toggle from the
            dashboard once your API key is saved.
          </p>
        </div>

        {/* Provider (read-only for now) */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide">
            Provider
          </label>
          <div className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm text-zinc-300">
            <span className="text-base">🤖</span>
            Anthropic
          </div>
        </div>

        {/* Model selector */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide">
            Model
          </label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm text-zinc-200 focus:outline-none focus:ring-1 focus:ring-zinc-500"
          >
            {ANTHROPIC_MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {/* API Key */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setTestState("idle");
              setTestMsg("");
            }}
            placeholder="sk-ant-..."
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-500"
          />
        </div>

        {/* Test + Save */}
        <div className="flex items-center gap-3">
          <button
            onClick={testConnection}
            disabled={!apiKey || testState === "loading"}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-zinc-600 text-zinc-300 hover:bg-zinc-700 disabled:opacity-40 transition-colors"
          >
            {testState === "loading" ? "Testing..." : "Test connection"}
          </button>

          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving..." : saved ? "Saved!" : "Save"}
          </button>

          {testState === "ok" && (
            <span className="text-xs text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
              {testMsg}
            </span>
          )}
          {testState === "error" && (
            <span className="text-xs text-red-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />
              {testMsg}
            </span>
          )}
        </div>

        <p className="text-xs text-zinc-500">
          The API key is stored in your Supabase database and read by the VPS bot at runtime.
          After saving, enable the LLM Filter toggle from the dashboard header.
        </p>
      </section>
    </div>
  );
}
