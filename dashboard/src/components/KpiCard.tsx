"use client";

interface KpiCardProps {
  label: string;
  value: string;
  subValue?: string;
  color?: "green" | "red" | "blue" | "default";
}

const colorMap = {
  green: "var(--green)",
  red: "var(--red)",
  blue: "var(--blue)",
  default: "var(--text-primary)",
};

export default function KpiCard({ label, value, subValue, color = "default" }: KpiCardProps) {
  return (
    <div className="rounded-xl p-4 border"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
      <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-secondary)" }}>
        {label}
      </p>
      <p className="text-2xl font-bold" style={{ color: colorMap[color] }}>
        {value}
      </p>
      {subValue && (
        <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
          {subValue}
        </p>
      )}
    </div>
  );
}
