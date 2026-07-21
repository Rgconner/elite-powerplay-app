/**
 * Target List tab — combines Power Selector, Reference System, and System List Input
 * to show scored targets from a Power's perspective in a pill-card layout.
 *
 * Each card shows the system name, PP state, PLAT/BOOM enrichment badges,
 * score badge, progress bar, merits, and reinforcement/undermining stats.
 */

import { useState, useEffect, useMemo } from "react";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { useSelectionState } from "../hooks/useSelectionState";
import PowerSelector from "../components/PowerSelector";
import RefSystemSelector from "../components/RefSystemSelector";
import SystemListInput from "../components/SystemListInput";
import { computeTargetScore, meritsToNextState } from "../utils/scoring";
import {
  PPBadge, ProgressBar, TargetScoreBadge, MeritsCell,
  PlatBadge, BoomBadge,
} from "../components/SharedCells";
import { getSpanshEnrichmentBatch, SpanshEnrichment } from "../api/spansh";

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

interface SortSpec {
  col: string;
  dir: SortDir;
}

// ── Sort button config ────────────────────────────────────────────────────

interface SortOption {
  col: string;
  label: string;
}

const SORT_OPTIONS: SortOption[] = [
  { col: "score",            label: "Score" },
  { col: "name",             label: "Name" },
  { col: "power_state",      label: "State" },
  { col: "control_progress", label: "Progress" },
  { col: "distance",         label: "Dist LY" },
  { col: "merits",           label: "Merits" },
  { col: "reinforcement",    label: "Reinf." },
  { col: "undermining",      label: "Underm." },
];

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

  // Sort state
  const [sort, setSort] = useState<SortSpec>({ col: "score", dir: "desc" });

  // Enrichment state: map system_id64 → { has_platinum, has_boom }
  const [enrichment, setEnrichment] = useState<Record<number, SpanshEnrichment>>({});
  const [enriching,  setEnriching]  = useState(false);
  const [enrichDone, setEnrichDone] = useState(false);

  // Fetch systems for the selected power when power or ref changes
  useEffect(() => {
    if (!powerName) { setAllSystems([]); return; }
    setLoading(true); setError(null);
    setEnrichment({});
    setEnriching(false);
    setEnrichDone(false);
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

  // Fetch Spansh enrichment data
  useEffect(() => {
    if (enriched.length === 0 || enrichDone) return;
    setEnriching(true);

    const ids = enriched.map(r => r.system_id64);
    getSpanshEnrichmentBatch(ids)
      .then(result => {
        setEnrichment(result);
        setEnrichDone(true);
      })
      .catch(() => {
        // Silently fail — enrichment is a nice-to-have
        setEnrichDone(true);
      })
      .finally(() => setEnriching(false));
  }, [enriched, enrichDone]);

  // Sort
  const sorted = useMemo(() => {
    return [...enriched].sort((a, b) => {
      const { col, dir } = sort;
      if (col === "name")              return cmp(a.name, b.name, dir);
      if (col === "score")             return cmp(a.score, b.score, dir);
      if (col === "distance")          return cmp(a.distance_ly, b.distance_ly, dir);
      if (col === "merits")            return cmp(a.meritsRemaining, b.meritsRemaining, dir);
      if (col === "control_progress")  return cmp(a.control_progress, b.control_progress, dir);
      if (col === "reinforcement")     return cmp(a.reinforcement, b.reinforcement, dir);
      if (col === "undermining")       return cmp(a.undermining, b.undermining, dir);
      if (col === "power_state")       return cmp(a.power_state, b.power_state, dir);
      return 0;
    });
  }, [enriched, sort]);

  function handleSort(col: string) {
    setSort(prev => ({
      col,
      dir: prev.col === col ? (prev.dir === "asc" ? "desc" : "asc") : "desc",
    }));
  }

  const showDist = !!refSystem;

  // ── Render ───────────────────────────────────────────────────────────────

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
          and merit progression toward the next state. Sort by clicking the column buttons.
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

      {/* ── Sort bar — pill-style column buttons ───────────────────────── */}
      {sorted.length > 0 && (
        <div style={{
          display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center",
          marginBottom: 10, fontSize: 11,
        }}>
          <span style={{ color: "#57606a", fontWeight: 600, marginRight: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Sort:
          </span>
          {SORT_OPTIONS.map(opt => {
            // Hide distance sort when no ref system
            if (opt.col === "distance" && !showDist) return null;
            const active = sort.col === opt.col;
            return (
              <button
                key={opt.col}
                onClick={() => handleSort(opt.col)}
                style={{
                  padding: "4px 10px", fontSize: 11, borderRadius: 4,
                  cursor: "pointer", border: active ? "1px solid #58a6ff" : "1px solid #30363d",
                  background: active ? "#051d2c" : "#161b22",
                  color: active ? "#58a6ff" : "#8b949e",
                  fontWeight: active ? 700 : 400,
                  whiteSpace: "nowrap",
                }}
              >
                {opt.label} {active ? (sort.dir === "asc" ? "↑" : "↓") : ""}
              </button>
            );
          })}

          {/* Enrichment status */}
          {enriching && (
            <span style={{ marginLeft: 8, color: "#4A90D9", fontSize: 11 }}>
              🔍 Spansh…
            </span>
          )}
          {enrichDone && Object.keys(enrichment).length > 0 && (
            <span style={{ marginLeft: 8, color: "#57606a", fontSize: 11 }}>
              ✓ {Object.values(enrichment).filter(e => e.has_platinum || e.has_boom).length} enriched
            </span>
          )}
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

      {/* ── Pill cards ───────────────────────────────────────────────────── */}
      {sorted.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {sorted.map((row) => {
            const r   = row.reinforcement ?? 0;
            const u   = row.undermining   ?? 0;
            const net = r - u;

            // Background tint by score tier
            const rowBg = row.score >= 80  ? "#1a0000"
                        : row.score >= 60  ? "#150c00"
                        : "#0d1117";

            const enc = enrichment[row.system_id64];
            const hasPlat = enc?.has_platinum ?? false;
            const hasBoom = enc?.has_boom ?? false;

            return (
              <div key={row.system_id64} style={{
                padding: "10px 14px", borderRadius: 8,
                background: rowBg, border: "1px solid #30363d",
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                {/* ── Header row ───────────────────────────── */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                }}>
                  {/* Score badge */}
                  <TargetScoreBadge score={row.score} />

                  {/* System name → Inara */}
                  <a
                    href={`https://inara.cz/elite/star/?search=${encodeURIComponent(row.name)}`}
                    target="_blank" rel="noreferrer"
                    style={{ color: "#58a6ff", textDecoration: "none", fontWeight: 600, fontSize: 13, flex: 1 }}
                  >
                    {row.name}
                  </a>

                  {/* PP State */}
                  <PPBadge state={row.power_state} />

                  {/* PLAT badge */}
                  {hasPlat && <PlatBadge />}

                  {/* BOOM badge */}
                  {hasBoom && <BoomBadge />}

                  {/* Merits remaining */}
                  <span style={{ fontSize: 11, color: "#8b949e", whiteSpace: "nowrap" }}>
                    Merits: <MeritsCell merits={row.meritsRemaining} />
                  </span>
                </div>

                {/* ── Progress bar ──────────────────────────── */}
                <ProgressBar value={row.control_progress} />

                {/* ── Stats row ─────────────────────────────── */}
                <div style={{
                  display: "flex", gap: 16, fontSize: 11, color: "#8b949e",
                  flexWrap: "wrap", alignItems: "center",
                }}>
                  {showDist && row.distance_ly != null && (
                    <span>📍 {row.distance_ly.toFixed(1)} LY</span>
                  )}
                  <span>
                    Reinf: <strong style={{ color: "#4AD94A" }}>{r > 0 ? r.toLocaleString() : "—"}</strong>
                  </span>
                  <span>
                    Underm: <strong style={{ color: u > r ? "#D94A4A" : u > 0 ? "#D9A84A" : "#555" }}>
                      {u > 0 ? u.toLocaleString() : "—"}
                    </strong>
                  </span>
                  {(r > 0 || u > 0) && (
                    <span>
                      Net: <strong style={{ color: net >= 0 ? "#4AD94A" : "#D94A4A" }}>
                        {net >= 0 ? "+" : ""}{net.toLocaleString()}
                      </strong>
                    </span>
                  )}
                  <span style={{ color: "#57606a", marginLeft: "auto" }}>
                    Score: <strong>{row.score.toFixed(1)}</strong>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}