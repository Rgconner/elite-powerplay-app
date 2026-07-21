/**
 * Target List tab — combines Power Selector, Reference System, and System List Input
 * to show scored targets from a Power's perspective.
 */
import { useState, useEffect, useMemo } from "react";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { useSelectionState } from "../hooks/useSelectionState";
import PowerSelector from "../components/PowerSelector";
import RefSystemSelector from "../components/RefSystemSelector";
import SystemListInput from "../components/SystemListInput";
import { computeTargetScore, meritsToNextState } from "../utils/scoring";
import {
  PPBadge, ProgressBar, TargetScoreBadge, MeritsCell, Th,
} from "../components/SharedCells";

// ── Types ─────────────────────────────────────────────────────────────────

type SortDir = "asc" | "desc";

interface TargetRow {
  system_id64: number;
  name: string;
  x: number;
  y: number;
  z: number;
  power_state: string | null;
  control_progress: number | null;
  reinforcement: number | null;
  undermining: number | null;
  distance_ly: number | null;
  score: number;
  meritsRemaining: number;
  meritsNeeded: number;
}

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

// ── Main component ─────────────────────────────────────────────────────────

export default function TargetListView() {
  const { powerName, refSystem, systemList, setPower, setRef, setSystemList } = useSelectionState();

  const [allSystems,      setAllSystems]      = useState<PPSystemEntry[]>([]);
  const [loading,         setLoading]         = useState(false);
  const [error,           setError]           = useState<string | null>(null);
  const [sortKey,         setSortKey]         = useState<string>("score");
  const [sortDir,         setSortDir]         = useState<SortDir>("desc");

  // Fetch systems for the selected power when power or ref changes
  useEffect(() => {
    if (!powerName) { setAllSystems([]); return; }
    setLoading(true); setError(null);
    getPowerSystems(powerName, refSystem?.id)
      .then(setAllSystems)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [powerName, refSystem?.id]);

  // Filter by system list (if any names are validated)
  const displaySystems = useMemo(() => {
    if (systemList.length === 0) return allSystems;
    const nameSet = new Set(systemList.map(n => n.toLowerCase()));
    return allSystems.filter(s => nameSet.has(s.name.toLowerCase()));
  }, [allSystems, systemList]);

  // Enrich with computed score
  const enriched = useMemo<TargetRow[]>(() => {
    return displaySystems.map(sys => {
      const score = computeTargetScore({
        control_progress: sys.control_progress,
        power_state: sys.power_state,
        distance_ly: sys.distance_from_center,
      });
      const { meritsRemaining, meritsNeeded } = meritsToNextState(
        sys.power_state,
        sys.control_progress ?? 0,
      );
      return {
        system_id64: sys.system_id64,
        name: sys.name,
        x: sys.x,
        y: sys.y,
        z: sys.z,
        power_state: sys.power_state,
        control_progress: sys.control_progress,
        reinforcement: sys.reinforcement,
        undermining: sys.undermining,
        distance_ly: sys.distance_from_center,
        score,
        meritsRemaining,
        meritsNeeded,
      };
    });
  }, [displaySystems]);

  // Sort
  const sorted = useMemo(() => {
    return [...enriched].sort((a, b) => {
      if (sortKey === "name") return cmp(a.name, b.name, sortDir);
      if (sortKey === "score") return cmp(a.score, b.score, sortDir);
      if (sortKey === "distance") return cmp(a.distance_ly, b.distance_ly, sortDir);
      if (sortKey === "merits") return cmp(a.meritsRemaining, b.meritsRemaining, sortDir);
      if (sortKey === "control_progress") return cmp(a.control_progress, b.control_progress, sortDir);
      return cmp((a as unknown as Record<string, unknown>)[sortKey], (b as unknown as Record<string, unknown>)[sortKey], sortDir);
    });
  }, [enriched, sortKey, sortDir]);

  function handleSort(col: string) {
    if (col === sortKey) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(col); setSortDir("desc"); }
  }

  const showDist = !!refSystem;

  return (
    <div style={{
      padding: "16px 20px", background: "#0d1117", minHeight: "calc(100vh - 44px)",
      fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3",
    }}>
      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div style={{
        background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
        padding: "14px 16px", marginBottom: 14, fontSize: 12,
        display: "flex", flexDirection: "column", gap: 12,
      }}>
        {/* Title */}
        <div style={{ fontSize: 14, fontWeight: 700, color: "#e6edf3", marginBottom: 2 }}>
          🎯 Target List — Score & Prioritise Systems
        </div>
        <p style={{ margin: 0, color: "#8b949e", lineHeight: 1.5 }}>
          Select a Power, optionally set a reference system, then paste or type system names below.
          The score combines control progress (higher = better), distance from reference (closer = better),
          and merit progression toward the next state. Sort by any column.
        </p>

        {/* Row 1: Power + Ref */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <PowerSelector value={powerName} onChange={setPower} />
          <RefSystemSelector value={refSystem} onChange={setRef} />
          {loading && <span style={{ fontSize: 13, color: "#8b949e" }}>Loading systems…</span>}
          {error && <span style={{ fontSize: 13, color: "#D94A4A" }}>{error}</span>}
        </div>

        {/* Row 2: System list input */}
        <SystemListInput value={systemList} onChange={setSystemList} powerName={powerName} />
      </div>

      {/* ── Score explanation panel ──────────────────────────────────────── */}
      {enriched.length > 0 && (
        <div style={{
          background: "#0d2a4a22", border: "1px solid #1f6feb33", borderRadius: 6,
          padding: "8px 14px", marginBottom: 10, display: "flex", flexWrap: "wrap", gap: "4px 16px",
          fontSize: 11, color: "#8b949e", alignItems: "center",
        }}>
          <span style={{ color: "#4A90D9", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Score Components
          </span>
          <span>📊 Progress: up to 50 pts (higher control = better)</span>
          <span>📍 Distance: up to 30 pts (≤100 LY = full bonus)</span>
          <span>🏆 Merits: up to 20 pts (closer to next state = better)</span>
          <span style={{ marginLeft: "auto", color: "#e6edf3" }}>
            {enriched.length} system{enriched.length !== 1 ? "s" : ""}
            {systemList.length > 0 && ` · ${systemList.length} in list`}
            {refSystem && ` · ref: ${refSystem.name}`}
          </span>
        </div>
      )}

      {/* ── Empty states ─────────────────────────────────────────────────── */}
      {!powerName && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 24 }}>
          Select a Power above to see its systems.
        </p>
      )}
      {powerName && !loading && allSystems.length === 0 && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 8 }}>
          No systems found for {powerName}. Run a Spansh PP ingest from the Admin panel first.
        </p>
      )}
      {powerName && !loading && allSystems.length > 0 && enriched.length === 0 && systemList.length > 0 && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 8 }}>
          None of the {systemList.length} system{systemList.length !== 1 ? "s" : ""} in your list were found under {powerName}. Check names or clear the filter.
        </p>
      )}

      {/* ── Table ────────────────────────────────────────────────────────── */}
      {sorted.length > 0 && (
        <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid #30363d" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <Th col="score"              label="Score"      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={80}
                    title="Priority score: higher = better target. Combines progress, distance, and merit completion." />
                <Th col="name"               label="System"     sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="power_state"        label="State"      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={120} />
                <Th col="control_progress"   label="Progress"   sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={100}
                    title="Control progress toward next state. Higher = closer to fortifying up." />
                {showDist && <Th col="distance" label="Dist LY" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={80} />}
                <Th col="merits"             label="Merits Remaining" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={130}
                    title="Merits needed to reach the next state. Lower = closer to upgrading." />
                <Th col="reinforcement"      label="Reinf."     sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={80} />
                <Th col="undermining"        label="Underm."    sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={80} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => {
                const r   = row.reinforcement ?? 0;
                const u   = row.undermining   ?? 0;
                const rowBg = row.score >= 80  ? "#1a0000"
                            : row.score >= 60  ? "#150c00"
                            : i % 2 === 0 ? "#0d1117" : "#161b22";
                return (
                  <tr key={row.system_id64} style={{ background: rowBg }}>
                    {/* Score badge */}
                    <td style={{ padding: "8px 6px" }}>
                      <TargetScoreBadge score={row.score} />
                    </td>

                    {/* System name → EDSM */}
                    <td style={{ padding: "8px 10px", fontWeight: 500, whiteSpace: "nowrap" }}>
                      <a
                        href={`https://inara.cz/elite/star/?search=${encodeURIComponent(row.name)}`}
                        target="_blank" rel="noreferrer"
                        style={{ color: "#58a6ff", textDecoration: "none" }}
                      >
                        {row.name}
                      </a>
                    </td>

                    {/* PP State */}
                    <td style={{ padding: "8px 10px" }}>
                      <PPBadge state={row.power_state} />
                    </td>

                    {/* Control progress bar */}
                    <td style={{ padding: "8px 10px" }}>
                      <ProgressBar value={row.control_progress} />
                    </td>

                    {/* Distance */}
                    {showDist && (
                      <td style={{ padding: "8px 10px", textAlign: "right", color: "#8b949e", fontVariantNumeric: "tabular-nums" }}>
                        {row.distance_ly != null ? `${row.distance_ly.toFixed(1)}` : "—"}
                      </td>
                    )}

                    {/* Merits remaining */}
                    <td style={{ padding: "8px 10px", textAlign: "right" }}>
                      <MeritsCell merits={row.meritsRemaining} />
                    </td>

                    {/* Reinforcement */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: "#4AD94A", fontVariantNumeric: "tabular-nums" }}>
                      {r > 0 ? r.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Undermining */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: u > r ? "#D94A4A" : u > 0 ? "#D9A84A" : "#555", fontVariantNumeric: "tabular-nums" }}>
                      {u > 0 ? u.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
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