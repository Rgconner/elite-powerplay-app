import { useState, useEffect, useMemo } from "react";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { getRecommendations, RecommendationsResponse, RecommendationItem } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor, PP_STATE_LABELS } from "../constants/ppColors";
import PowerSelector from "../components/PowerSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import RecommendationPanel from "../components/RecommendationPanel";

type SortDir = "asc" | "desc";

// ── Helpers ────────────────────────────────────────────────────────────────

function cmp(a: unknown, b: unknown, dir: SortDir): number {
  const f = dir === "asc" ? 1 : -1;
  if (a == null && b == null) return 0;
  if (a == null) return f;
  if (b == null) return -f;
  if (typeof a === "string" && typeof b === "string") return f * a.localeCompare(b);
  if (typeof a === "number" && typeof b === "number") return f * (a - b);
  return 0;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function PPBadge({ state }: { state: string | null }) {
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

/** Urgency badge derived from the matching recommendation item. */
function UrgencyBadge({ recoItem }: { recoItem: RecommendationItem | null | undefined }) {
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

function ExpandBadge() {
  return (
    <span style={{
      background: "#0d2a4a", color: "#4A90D9", border: "1px solid #1f6feb44",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      EXPAND
    </span>
  );
}

/** Compact progress bar with value label. */
function ProgressBar({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: "#555" }}>—</span>;
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = value <= 0   ? "#D94A4A"
              : value < 0.2  ? "#FF8C00"
              : value < 0.5  ? "#D9A84A"
              : value < 1.0  ? "#4AD94A"
              : "#00E5CC";
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

/** Days-to-failure cell. */
function DaysCell({ days }: { days: number | null | undefined }) {
  if (days == null) return <span style={{ color: "#555" }}>—</span>;
  if (days === 0) return <span style={{ color: "#FF4444", fontWeight: 800 }}>NOW</span>;
  const color = days < 2 ? "#FF4444" : days < 5 ? "#FF8C00" : "#D9A84A";
  return <span style={{ color, fontWeight: 600 }}>{days.toFixed(1)}d</span>;
}

function ThreatArrow({ trend }: { trend: string | undefined }) {
  if (trend === "worsening") return <span style={{ color: "#D94A4A", fontSize: 14 }} title="Situation worsening">↗</span>;
  if (trend === "improving") return <span style={{ color: "#4AD94A", fontSize: 14 }} title="Situation improving">↘</span>;
  return <span style={{ color: "#444" }}>—</span>;
}

function Th({ col, label, sortKey, sortDir, onSort, width, title }: {
  col: string; label: string; sortKey: string; sortDir: SortDir;
  onSort: (k: string) => void; width?: number; title?: string;
}) {
  const active = col === sortKey;
  return (
    <th
      onClick={() => onSort(col)}
      title={title}
      style={{
        padding: "10px 10px", textAlign: "left", fontSize: 11, fontWeight: 700,
        color: active ? "#e6edf3" : "#8b949e", textTransform: "uppercase",
        letterSpacing: "0.05em", cursor: "pointer", whiteSpace: "nowrap",
        background: "#161b22", borderBottom: "2px solid #30363d", width,
        userSelect: "none",
      }}
    >
      {label}
      <span style={{ marginLeft: 3, opacity: active ? 1 : 0.3 }}>
        {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
      </span>
    </th>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function TableView() {
  const { powerName, centerSystem, setPower, setCenter } = useSelectionState();

  const [systems,         setSystems]         = useState<PPSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loadingSystems,  setLoadingSystems]  = useState(false);
  const [loadingRecos,    setLoadingRecos]    = useState(false);
  const [error,           setError]           = useState<string | null>(null);
  const [sortKey,         setSortKey]         = useState<string>("control_progress");
  const [sortDir,         setSortDir]         = useState<SortDir>("asc");

  // Build lookup maps from recommendations for O(1) row enrichment
  const fortifyMap = useMemo(() => {
    const m = new Map<string, RecommendationItem>();
    recommendations?.fortify.forEach(r => m.set(r.system_name, r));
    return m;
  }, [recommendations]);

  const expandSet = useMemo(
    () => new Set((recommendations?.expand ?? []).map(r => r.system_name)),
    [recommendations]
  );

  function getRecoType(name: string): "fortify" | "expand" | null {
    if (fortifyMap.has(name)) return "fortify";
    if (expandSet.has(name))  return "expand";
    return null;
  }

  useEffect(() => {
    if (!powerName) { setSystems([]); setRecommendations(null); return; }
    setLoadingSystems(true); setError(null);
    getPowerSystems(powerName, centerSystem?.id)
      .then(setSystems)
      .catch(e => setError(String(e)))
      .finally(() => setLoadingSystems(false));
  }, [powerName, centerSystem?.id]);

  useEffect(() => {
    if (!powerName) { setRecommendations(null); return; }
    setLoadingRecos(true);
    getRecommendations(powerName, centerSystem?.id)
      .then(setRecommendations)
      .catch(() => setRecommendations(null))
      .finally(() => setLoadingRecos(false));
  }, [powerName, centerSystem?.id]);

  // Default sort: by control_progress ascending (most at-risk first) when no center;
  // by distance ascending when a center is selected.
  useEffect(() => {
    setSortKey(centerSystem ? "distance_from_center" : "control_progress");
    setSortDir("asc");
  }, [centerSystem?.id]);

  function handleSort(col: string) {
    if (col === sortKey) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(col); setSortDir("asc"); }
  }

  const sorted = useMemo(() => {
    return [...systems].sort((a, b) => {
      if (sortKey === "recommendation") {
        return cmp(getRecoType(a.name), getRecoType(b.name), sortDir);
      }
      if (sortKey === "net") {
        const na = (a.reinforcement ?? 0) - (a.undermining ?? 0);
        const nb = (b.reinforcement ?? 0) - (b.undermining ?? 0);
        return cmp(na, nb, sortDir);
      }
      if (sortKey === "days_to_failure") {
        const da = fortifyMap.get(a.name)?.days_to_failure ?? Infinity;
        const db = fortifyMap.get(b.name)?.days_to_failure ?? Infinity;
        return cmp(da, db, sortDir);
      }
      return cmp((a as unknown as Record<string, unknown>)[sortKey], (b as unknown as Record<string, unknown>)[sortKey], sortDir);
    });
  }, [systems, sortKey, sortDir, fortifyMap, expandSet]);

  const showDist = !!centerSystem;

  return (
    <div style={{
      padding: "16px 20px", background: "#0d1117", minHeight: "calc(100vh - 44px)",
      fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3",
    }}>
      {/* Controls */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <PowerSelector value={powerName} onChange={setPower} />
        <CenterSystemSelector value={centerSystem} onChange={setCenter} />
        {loadingSystems && <span style={{ fontSize: 13, color: "#8b949e" }}>Loading systems…</span>}
        {error && <span style={{ fontSize: 13, color: "#D94A4A" }}>{error}</span>}
        {systems.length > 0 && !loadingSystems && (
          <span style={{ fontSize: 12, color: "#8b949e", marginLeft: "auto" }}>
            {systems.length} system{systems.length !== 1 ? "s" : ""}
            {powerName && ` · ${powerName}`}
            {centerSystem && ` · centered on ${centerSystem.name}`}
          </span>
        )}
      </div>

      {/* Recommendation panel */}
      <RecommendationPanel recommendations={recommendations} loading={loadingRecos} />

      {/* Empty states */}
      {!powerName && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 24 }}>
          Search for a Power above to populate the table.
        </p>
      )}
      {powerName && !loadingSystems && systems.length === 0 && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 8 }}>
          No systems found. Run a Spansh PP ingest from the Admin panel first.
        </p>
      )}

      {/* Table */}
      {systems.length > 0 && (
        <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid #30363d", marginTop: 4 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <Th col="name"               label="System"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="power_state"        label="State"         sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={110} />
                <Th col="control_progress"   label="Progress"      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={100}
                    title="Control progress toward next state (0–100%). Red=failing, teal=upgrade ready." />
                <Th col="days_to_failure"    label="Days"          sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={65}
                    title="Estimated days until state downgrade. NOW=failing this cycle." />
                <Th col="reinforcement"      label="Reinf."        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={90} />
                <Th col="undermining"        label="Underm."       sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={90} />
                <Th col="net"                label="Net R–U"       sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={90}
                    title="Net = Reinforcement minus Undermining. Positive=safe, negative=at risk." />
                <Th col="undermine_ratio"    label="Threat"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={70}
                    title="Undermining as % of reinforcement." />
                <Th col="threat_trend"       label="Trend"         sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={55}
                    title="Trend in control_progress across snapshots." />
                {showDist && <Th col="distance_from_center" label="Dist LY" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={80} />}
                <Th col="recommendation"     label="Action"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={100} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((sys, i) => {
                const reco     = getRecoType(sys.name);
                const recoItem = reco === "fortify" ? fortifyMap.get(sys.name) ?? null
                               : null;
                const r   = sys.reinforcement ?? 0;
                const u   = sys.undermining   ?? 0;
                const net = r - u;

                // Row background: tint critical/urgent rows
                const rowBg = recoItem && recoItem.score >= 950
                  ? "#1a0000"
                  : recoItem && recoItem.score >= 750
                  ? "#150c00"
                  : i % 2 === 0 ? "#0d1117" : "#161b22";

                return (
                  <tr key={sys.system_id64} style={{ background: rowBg }}>
                    {/* System name → EDSM link */}
                    <td style={{ padding: "8px 10px", fontWeight: 500, whiteSpace: "nowrap" }}>
                      <a
                        href={`https://www.edsm.net/en/system/id/-/name/${encodeURIComponent(sys.name)}`}
                        target="_blank" rel="noreferrer"
                        style={{ color: "#58a6ff", textDecoration: "none" }}
                      >
                        {sys.name}
                      </a>
                    </td>

                    {/* PP State */}
                    <td style={{ padding: "8px 10px" }}>
                      <PPBadge state={sys.power_state} />
                    </td>

                    {/* Control progress bar */}
                    <td style={{ padding: "8px 10px" }}>
                      <ProgressBar value={sys.control_progress} />
                    </td>

                    {/* Days to failure */}
                    <td style={{ padding: "8px 10px", textAlign: "center" }}>
                      <DaysCell days={recoItem?.days_to_failure} />
                    </td>

                    {/* Reinforcement */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: "#4AD94A", fontVariantNumeric: "tabular-nums" }}>
                      {r > 0 ? r.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Undermining */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: u > r ? "#D94A4A" : u > 0 ? "#D9A84A" : "#555", fontVariantNumeric: "tabular-nums" }}>
                      {u > 0 ? u.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Net R–U */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: net >= 0 ? "#4AD94A" : "#D94A4A", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                      {(r > 0 || u > 0) ? `${net >= 0 ? "+" : ""}${net.toLocaleString()}` : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Threat % */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: sys.undermine_ratio != null && sys.undermine_ratio > 0.6 ? "#D94A4A" : sys.undermine_ratio != null && sys.undermine_ratio > 0.3 ? "#D9A84A" : "#8b949e" }}>
                      {sys.undermine_ratio != null ? `${(sys.undermine_ratio * 100).toFixed(0)}%` : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Trend */}
                    <td style={{ padding: "8px 10px", textAlign: "center" }}>
                      <ThreatArrow trend={recoItem?.threat_trend} />
                    </td>

                    {/* Distance */}
                    {showDist && (
                      <td style={{ padding: "8px 10px", textAlign: "right", color: "#8b949e" }}>
                        {sys.distance_from_center != null ? `${sys.distance_from_center.toFixed(1)}` : "—"}
                      </td>
                    )}

                    {/* Action badge */}
                    <td style={{ padding: "8px 10px" }}>
                      {reco === "fortify" && <UrgencyBadge recoItem={recoItem} />}
                      {reco === "expand"  && <ExpandBadge />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
