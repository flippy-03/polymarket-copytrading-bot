"use client";

import type { TimeFilter } from "@/lib/types";

const FILTERS: { value: TimeFilter; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "1y", label: "1Y" },
  { value: "all", label: "All" },
];

interface Props {
  selected: TimeFilter;
  onChange: (f: TimeFilter) => void;
}

export default function TimeFilterBar({ selected, onChange }: Props) {
  return (
    <div className="flex gap-1 rounded-lg p-1" style={{ background: "var(--bg-secondary)" }}>
      {FILTERS.map(({ value, label }) => (
        <button key={value} onClick={() => onChange(value)}
          className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
          style={{
            background: selected === value ? "var(--bg-card)" : "transparent",
            color: selected === value ? "var(--text-primary)" : "var(--text-secondary)",
          }}>
          {label}
        </button>
      ))}
    </div>
  );
}
