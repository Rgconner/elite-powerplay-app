import React from "react";

export type LayoutMode = "actual" | "radial" | "force";

interface Props {
  value: LayoutMode;
  onChange: (mode: LayoutMode) => void;
}

const OPTIONS: { value: LayoutMode; label: string; title: string }[] = [
  { value: "actual", label: "Actual Coords", title: "Use real in-game x/y/z coordinates" },
  { value: "radial", label: "Distance Radial", title: "Place systems radially by distance from center" },
  { value: "force", label: "Force-Directed", title: "Spring-force layout based on proximity" },
];

export default function LayoutModeSelector({ value, onChange }: Props) {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <span style={{ fontSize: 12, color: "#57606a", marginRight: 4 }}>Layout:</span>
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          title={opt.title}
          onClick={() => onChange(opt.value)}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            borderRadius: 4,
            border: "1px solid #e5e7eb",
            background: value === opt.value ? "#3b82d4" : "#fff",
            color: value === opt.value ? "#fff" : "#57606a",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
