import React, { useState, useEffect, useMemo } from "react";
import { getFactionSystems, FactionSystemEntry } from "../api/factions";
import { getRecommendations, RecommendationsResponse } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor } from "../constants/ppColors";
import FactionSelector from "../components/FactionSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import RecommendationPanel from "../components/RecommendationPanel";

// ── Sorting helpers ─────────────────────────────────────────────────────────
type SortKey = "system_name" | "is_controlling" | "pp_state" | "pp_power" | "influence" | "distance_from_center" | "recommendation";
type SortDir = "asc" | "desc";

function cmp(a: unknown, b: unknown, dir: SortDir): number {
  const factor = dir === "asc" ? 1 : -1;
  if (a == null && b == null) return 0;
  if (a == null) return factor;
  if (b == null) return -factor;
  if (typeof a === "string" && typeof b === "string") return factor * a.localeCompare(b);
  if (typeof a === "number" && typeof b === "number") return factor * (a - b);
  if (typeof a === "boolean" && typeof b === "boolean") return factor * (a === b ? 0 : a ? -1 : 1);
  return 0;
}

// ── Small display components ─────────────────────────────────────────────────
function PPBadge({ state }: { state: string | null }) {
  if (!state) return <span style={{ color: "#999" }}>—</span>;
  return (
    <span style={{ background: ppStateColor(state), color: "#fff", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
      {state}
    </span>
  );
}

function RecoBadge({ type }: { type: "fortify" | "expand" | null }) {
  if (!type) return null;
  const bg = type === "fortify" ? "#D94A4A" : "#3b82d4";
  const label = type === "fortify" ? "Fortify" : "Expand";
  return (
    <span style={{ background: bg, color: "#fff", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
      {label}
    </span>
  );
}

function TrendArrow({ trend }: { trend: string }) {
  if (trend === "rising") return <span style={{ color: "#4AD94A" }}>↑</span>;
  if (trend === "falling") return <span style={{ color: "#D94A4A" }}>↓</span>;
  return <span style={{ color: "#999" }}>—</span>;
}

function SortIndicator({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (col !== sortKey) return <span style={{ color: "#ccc", marginLeft: 4 }}>↕</span>;
  return <span style={{ marginLeft: 4 }}>{sortDir === "asc" ? "↑" : "↓"}</span>;
}

// ── Column header ────────────────────────────────────────────────────────────
function Th({ col, label, sortKey, sortDir, onSort, width }: {
  col: SortKey; label: string; sortKey: SortKey; sortDir: SortDir;
  onSort: (k: SortKey) => void; width?: number;
}) {
  return (
    <th
      onClick={() => onSort(col)}
      style={{ padding: "10px 12px", textAlign: "left", fontSize: 12, fontWeight: 700, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.04em", cursor: "pointer", whiteSpace: "nowrap", background: "#f7f8fa", borderBottom: "2px solid #e5e7eb", width }}
    >
      {label}<SortIndicator col={col} sortKey={sortKey} sortDir={sortDir} />
    </th>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export default function TableView() {
  const { factionName, centerSystem, setFaction, setCenter } = useSelectionState();

  const [systems, setSystems] = useState<FactionSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loadingSystems, setLoadingSystems] = useState(false);
  const [loadingRecos, setLoadingRecos] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Default sort: distance asc when center is selected, else system name asc
  const [sortKey, setSortKey] = useState<SortKey>("system_name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Build sets for O(1) recommendation lookup
  const fortifySet = useMemo(() => new Set((recommendations?.fortify ?? []).map((r) => r.system_name)), [recommendations]);
  const expandSet = useMemo(() => new Set((recommendations?.expand ?? []).map((r) => r.system_name)), [recommendations]);

  function getRecoType(name: string): "fortify" | "expand" | null {
    if (fortifySet.has(name)) return "fortify";
    if (expandSet.has(name)) return "expand";
    return null;
  }

  // Fetch systems whenever faction or center changes
  useEffect(() => {
    if (!factionName) { setSystems([]); setRecommendations(null); return; }
    setLoadingSystems(true);
    setError(null);
    getFactionSystems(factionName, centerSystem?.id)
      .then(setSystems)
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingSystems(false));
  }, [factionName, centerSystem?.id]);

  // Fetch recommendations separately
  useEffect(() => {
    if (!factionName) { setRecommendations(null); return; }
    setLoadingRecos(true);
    getRecommendations(factionName, centerSystem?.id)
      .then(setRecommendations)
      .catch(() => setRecommendations(null))
      .finally(() => setLoadingRecos(false));
  }, [factionName, centerSystem?.id]);

  // Default sort key change based on whether center is selected
  useEffect(() => {
    setSortKey(centerSystem ? "distance_from_center" : "system_name");
    setSortDir("asc");
  }, [centerSystem?.id]);

  function handleSort(col: SortKey) {
    if (col === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(col); setSortDir("asc"); }
  }

  // Sort rows
  const sorted = useMemo(() => {
    return [...systems].sort((a, b) => {
      if (sortKey === "recommendation") {
        const rA = getRecoType(a.system_name);
        const rB = getRecoType(b.system_name);
        return cmp(rA, rB, sortDir);
      }
      return cmp(a[sortKey as keyof FactionSystemEntry], b[sortKey as keyof FactionSystemEntry], sortDir);
    });
  }, [systems, sortKey, sortDir, fortifySet, expandSet]);

  const showDistance = !!centerSystem;

  return (
    <div style={{ padding: "20px 24px", fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: "#1f2328" }}>
      {/* Selectors row */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
        <FactionSelector value={factionName} onChange={setFaction} />
        <CenterSystemSelector value={centerSystem} onChange={setCenter} />
        {loadingSystems && <span style={{ fontSize: 13, color: "#57606a" }}>Loading…</span>}
        {error && <span style={{ fontSize: 13, color: "#D94A4A" }}>{error}</span>}
      </div>

      {/* Recommendation panel */}
      <RecommendationPanel recommendations={recommendations} loading={loadingRecos} />

      {/* Empty state */}
      {!factionName && (
        <p style={{ color: "#57606a", fontSize: 14, marginTop: 24 }}>Search for a faction above to populate the table.</p>
      )}

      {/* Table */}
      {factionName && !loadingSystems && systems.length === 0 && (
        <p style={{ color: "#57606a", fontSize: 14, marginTop: 8 }}>No systems found for this faction. Data may not have been ingested yet.</p>
      )}

      {systems.length > 0 && (
        <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid #e5e7eb" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <Th col="system_name" label="System" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="is_controlling" label="Controls?" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={90} />
                <Th col="pp_state" label="PP State" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="pp_power" label="PP Power" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="influence" label="Influence" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={100} />
                <Th col="recommendation" label="Trend" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={70} />
                {showDistance && <Th col="distance_from_center" label="Distance (LY)" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={120} />}
                <Th col="recommendation" label="Action" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={100} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((sys, i) => {
                const reco = getRecoType(sys.system_name);
                const recoItem = reco === "fortify"
                  ? recommendations?.fortify.find((r) => r.system_name === sys.system_name)
                  : reco === "expand"
                  ? recommendations?.expand.find((r) => r.system_name === sys.system_name)
                  : null;
                return (
                  <tr key={sys.system_id64} style={{ background: i % 2 === 0 ? "#fff" : "#f7f8fa" }}>
                    <td style={{ padding: "9px 12px", fontWeight: 500 }}>
                      <a
                        href={`https://www.edsm.net/en/system/id/-/name/${encodeURIComponent(sys.system_name)}`}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: "#3b82d4", textDecoration: "none" }}
                      >
                        {sys.system_name}
                      </a>
                    </td>
                    <td style={{ padding: "9px 12px", textAlign: "center" }}>
                      {sys.is_controlling ? <span style={{ color: "#4AD94A", fontWeight: 700 }}>✓</span> : <span style={{ color: "#ccc" }}>—</span>}
                    </td>
                    <td style={{ padding: "9px 12px" }}><PPBadge state={sys.pp_state} /></td>
                    <td style={{ padding: "9px 12px", color: "#57606a" }}>{sys.pp_power ?? "—"}</td>
                    <td style={{ padding: "9px 12px" }}>
                      {sys.influence != null ? `${(sys.influence * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td style={{ padding: "9px 12px", textAlign: "center" }}>
                      <TrendArrow trend={recoItem?.influence_trend ?? "unknown"} />
                    </td>
                    {showDistance && (
                      <td style={{ padding: "9px 12px", textAlign: "right" }}>
                        {sys.distance_from_center != null ? `${sys.distance_from_center.toFixed(1)} LY` : "—"}
                      </td>
                    )}
                    <td style={{ padding: "9px 12px" }}><RecoBadge type={reco} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ padding: "8px 12px", fontSize: 12, color: "#57606a", borderTop: "1px solid #e5e7eb", background: "#f7f8fa" }}>
            {sorted.length} system{sorted.length !== 1 ? "s" : ""}
            {factionName && ` · ${factionName}`}
            {centerSystem && ` · centered on ${centerSystem.name}`}
          </div>
        </div>
      )}
    </div>
  );
}
