/** Reusable table-cell sub-components shared across pages. */
import type { CSSProperties } from "react";
import { ppStateColor, PP_STATE_LABELS } from "../constants/ppColors";
import type { RecommendationItem } from "../api/recommendations";

// ── PP State badge ─────────────────────────────────────────────────────────

export function PPBadge({ state }: { state: string | null }) {
  if (!state) return <span style={{ color: "#666" }}>—</span>;
  return (
    <span style={{
      background: ppStateColor(state), color: "#fff",
      borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600,
    }}>
      {PP_STATE_LABELS[state] ?? state}
    </span>
  );
}

// ── Contested badge ────────────────────────────────────────────────────────

export function ContestedBadge() {
  return (
    <span style={{
      background: "#2d1f00", color: "#FF8C00", border: "1px solid #FF8C0066",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      ⚔ CONTESTED
    </span>
  );
}

// ── Expand badge ───────────────────────────────────────────────────────────

export function ExpandBadge() {
  return (
    <span style={{
      background: "#0d2a4a", color: "#4A90D9", border: "1px solid #1f6feb44",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      EXPAND
    </span>
  );
}

// ── Urgency badge ──────────────────────────────────────────────────────────

export function UrgencyBadge({ recoItem }: { recoItem: RecommendationItem | null | undefined }) {
  if (!recoItem || recoItem.type !== "fortify") return null;
  const s = recoItem.score;
  const d = recoItem.days_to_failure;
  let label: string, bg: string, fg: string;
  if (s >= 950 || d === 0)                    { label = "CRITICAL";  bg = "#3d0000"; fg = "#FF4444"; }
  else if (s >= 750 || (d != null && d < 2))  { label = "URGENT";    bg = "#3d1a00"; fg = "#FF8C00"; }
  else if (s >= 550 || (d != null && d < 5))  { label = "WARNING";   bg = "#2a2000"; fg = "#D9A84A"; }
  else if (s >= 250)                           { label = "MONITOR";   bg = "#1a1a2e"; fg = "#8899AA"; }
  else if (s >= 100)                           { label = "REINFORCE"; bg = "#0d2e17"; fg = "#4AD94A"; }
  else return null;
  return (
    <span style={{
      background: bg, color: fg, border: `1px solid ${fg}66`,
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 800,
      letterSpacing: "0.05em",
    }}>
      {label}
    </span>
  );
}

// ── Progress bar ───────────────────────────────────────────────────────────

export function ProgressBar({ value, thresholds }: {
  value: number | null;
  thresholds?: { critical: number; high: number; medium: number };
}) {
  if (value == null) return <span style={{ color: "#555" }}>—</span>;
  const pct = Math.max(0, Math.min(1, value)) * 100;

  let color: string;
  if (thresholds) {
    color = value <= 0                       ? "#FF4444"
          : value <= thresholds.critical     ? "#FF4444"
          : value <= thresholds.high         ? "#FF8C00"
          : value <= thresholds.medium       ? "#D9A84A"
          : value < 1.0                      ? "#4AD94A"
          : "#00E5CC";
  } else {
    color = value <= 0   ? "#D94A4A"
          : value < 0.2  ? "#FF8C00"
          : value < 0.5  ? "#D9A84A"
          : value < 1.0  ? "#4AD94A"
          : "#00E5CC";
  }

  return (
    <div style={{ minWidth: 70 }}>
      <div style={{ fontSize: 11, color, fontWeight: 600, textAlign: "right", marginBottom: 1 }}>
        {(value * 100).toFixed(1)}%
        {value >= 1.0 && <span title="Upgrade threshold crossed"> ✓</span>}
        {value <= 0   && <span title="At downgrade threshold"> !</span>}
      </div>
      <div style={{ height: 3, borderRadius: 2, background: "#2a2a3a", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

// ── Days cell ──────────────────────────────────────────────────────────────

export function DaysCell({ days }: { days: number | null | undefined }) {
  if (days == null) return <span style={{ color: "#555" }}>—</span>;
  if (days === 0) return <span style={{ color: "#FF4444", fontWeight: 800 }}>NOW</span>;
  const color = days < 2 ? "#FF4444" : days < 5 ? "#FF8C00" : "#D9A84A";
  return <span style={{ color, fontWeight: 600 }}>{days.toFixed(1)}d</span>;
}

// ── PLAT badge ────────────────────────────────────────────────────────────

export function PlatBadge() {
  return (
    <span
      title="Platinum signal in a metallic ring"
      style={{
        background: "#0d2e17", color: "#4AD94A", border: "1px solid #4AD94A44",
        borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
        cursor: "help",
      }}
    >
      🪨 PLAT
    </span>
  );
}

// ── BOOM badge ────────────────────────────────────────────────────────────

export function BoomBadge() {
  return (
    <span style={{
      background: "#2a2000", color: "#D9A84A", border: "1px solid #D9A84A44",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      💥 BOOM
    </span>
  );
}

// ── PRIST badge (Pristine reserve level) ─────────────────────────────────

export function PristBadge() {
  return (
    <span style={{
      background: "#0d2a4a", color: "#00E5CC", border: "1px solid #00E5CC44",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      💎 PRIST
    </span>
  );
}

// ── Threat arrow ───────────────────────────────────────────────────────────

export function ThreatArrow({ trend }: { trend: string | undefined }) {
  if (trend === "worsening") return <span style={{ color: "#D94A4A", fontSize: 14 }} title="Situation worsening">↗</span>;
  if (trend === "improving") return <span style={{ color: "#4AD94A", fontSize: 14 }} title="Situation improving">↘</span>;
  return <span style={{ color: "#444" }}>—</span>;
}

// ── Sortable table header ──────────────────────────────────────────────────

const headerStyle: CSSProperties = {
  padding: "10px 10px", textAlign: "left", fontSize: 11, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: "0.05em", cursor: "pointer",
  whiteSpace: "nowrap", background: "#161b22", borderBottom: "2px solid #30363d",
  userSelect: "none",
};

export function Th({ col, label, sortKey, sortDir, onSort, width, title }: {
  col: string; label: string; sortKey: string; sortDir: "asc" | "desc";
  onSort: (k: string) => void; width?: number; title?: string;
}) {
  const active = col === sortKey;
  return (
    <th
      onClick={() => onSort(col)}
      title={title}
      style={{ ...headerStyle, color: active ? "#e6edf3" : "#8b949e", width }}
    >
      {label}
      <span style={{ marginLeft: 3, opacity: active ? 1 : 0.3 }}>
        {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
      </span>
    </th>
  );
}

// ── Score badge for Target List ────────────────────────────────────────────

export function TargetScoreBadge({ score }: { score: number }) {
  let label: string, bg: string, fg: string;
  if (score >= 100)      { label = "MAX";         bg = "#3d0000"; fg = "#FF4444"; }
  else if (score >= 80)  { label = "PRIME";       bg = "#3d0000"; fg = "#FF4444"; }
  else if (score >= 60)  { label = "HIGH";        bg = "#3d1a00"; fg = "#FF8C00"; }
  else if (score >= 40)  { label = "MEDIUM";      bg = "#2a2000"; fg = "#D9A84A"; }
  else if (score >= 20)  { label = "LOW";         bg = "#1a1a2e"; fg = "#8899AA"; }
  else                   { label = "MINIMAL";     bg = "#161b22"; fg = "#555566"; }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-start" }}>
      <span style={{
        background: bg, color: fg, border: `1px solid ${fg}66`,
        borderRadius: 3, padding: "1px 7px", fontSize: 10, fontWeight: 800,
        letterSpacing: "0.05em",
      }}>
        {label}
      </span>
      <span style={{ fontSize: 11, color: "#8b949e", paddingLeft: 1 }}>
        {score.toFixed(1)}
      </span>
    </div>
  );
}

// ── Stale badge ────────────────────────────────────────────────────────────

const STALE_THRESHOLD_DAYS = 7;

export function StaleBadge({ snapshotTime }: { snapshotTime: string | null }) {
  if (!snapshotTime) return null;

  const now = Date.now();
  const snap = new Date(snapshotTime).getTime();
  if (isNaN(snap)) return null;

  const ageDays = (now - snap) / (1000 * 60 * 60 * 24);
  if (ageDays <= STALE_THRESHOLD_DAYS) return null;

  return (
    <span
      title="This system's Power Play data is over 7 days old. Data may not reflect current game state. Click Refresh to update."
      style={{
        background: "#2d1a00", color: "#FF8C00", border: "1px solid #FF8C0044",
        borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
        cursor: "help",
      }}
    >
      ⚠ STALE
    </span>
  );
}

// ── Merits cell ────────────────────────────────────────────────────────────

export function MeritsCell({ merits }: { merits: number }) {
  const color = merits <= 0 ? "#4AD94A" : merits < 50_000 ? "#D9A84A" : merits < 120_000 ? "#FF8C00" : "#FF4444";
  return (
    <span style={{ color, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
      {merits > 0 ? merits.toLocaleString() : "✓"}
    </span>
  );
}