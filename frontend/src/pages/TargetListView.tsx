/**
 * Target List tab — combines Power Selector, Reference System, and System List Input
 * to show scored targets from a Power's perspective in a pill-card layout.
 *
 * Each card shows the system name, PP state, PLAT/BOOM enrichment badges,
 * score badge, progress bar, merits, and reinforcement/undermining stats.
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import { getPowerSystems, refreshStaleSystems, PPSystemEntry } from "../api/powers";
import { useSelectionState } from "../hooks/useSelectionState";
import PowerSelector from "../components/PowerSelector";
import RefSystemSelector from "../components/RefSystemSelector";
import SystemListInput from "../components/SystemListInput";
import { computeTargetScore, meritsToNextState, meritsToSafety } from "../utils/scoring";
import { netValue } from "../utils/decay";
import { CP_DECAY_COLOR } from "../constants/ppColors";
import {
  PPBadge, ProgressBar, TargetScoreBadge, MeritsCell,
  PlatBadge, BoomBadge, PristBadge, StaleBadge,
} from "../components/SharedCells";
import { getSpanshEnrichmentBatch, clearEnrichmentCache, SpanshEnrichment } from "../api/spansh";
import { getAdminToken } from "../api/admin";

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
  cp_decay: number | null;
  distance_ly: number | null;
  score: number;
  meritsRemaining: number;
  meritsNeeded: number;
  snapshot_time: string | null;
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

const STALE_THRESHOLD_DAYS = 7;

function isStale(snapshotTime: string | null): boolean {
  if (!snapshotTime) return false;
  const snap = new Date(snapshotTime).getTime();
  if (isNaN(snap)) return false;
  const ageDays = (Date.now() - snap) / (1000 * 60 * 60 * 24);
  return ageDays > STALE_THRESHOLD_DAYS;
}

// ── Main component ─────────────────────────────────────────────────────────

export default function TargetListView() {
  const { powerName, refSystem, systemList, setPower, setRef, setSystemList } = useSelectionState();

  // Clear system list when a new power is selected (previously-entered names
  // belong to a different power and would incorrectly filter the results)
  const handleSetPower = useCallback((name: string | null) => {
    setPower(name);
    if (name !== powerName) setSystemList([]);
  }, [powerName, setPower, setSystemList]);

  const [allSystems,      setAllSystems]      = useState<PPSystemEntry[]>([]);
  const [loading,         setLoading]         = useState(false);
  const [error,           setError]           = useState<string | null>(null);

  // Sort state
  const [sort, setSort] = useState<SortSpec>({ col: "score", dir: "desc" });

  // Enrichment state: map system_id64 → { has_platinum, has_boom }
  const [enrichment, setEnrichment] = useState<Record<number, SpanshEnrichment>>({});
  const [enriching,  setEnriching]  = useState(false);
  const [caching,    setCaching]    = useState(false);

  // Stale refresh state
  const [refreshing, setRefreshing] = useState(false);

  // Admin state — show cache management buttons only for logged-in admins
  const isAdmin = getAdminToken() !== null;

  // Fetch systems for the selected power when power or ref changes
  useEffect(() => {
    if (!powerName) { setAllSystems([]); return; }
    setLoading(true); setError(null);
    setEnrichment({});
    setEnriching(false);
    setRefreshing(false);
    getPowerSystems(powerName, refSystem?.id)
      .then(setAllSystems)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [powerName, refSystem?.id]);

  // Auto-refresh stale systems after they load
  useEffect(() => {
    if (!powerName || allSystems.length === 0) return;
    const staleIds = allSystems
      .filter(s => isStale(s.snapshot_time))
      .map(s => s.system_id64);
    if (staleIds.length === 0) return;

    setRefreshing(true);
    refreshStaleSystems(staleIds)
      .then(() => {
        // Wait a moment for background refresh, then re-fetch
        setTimeout(() => {
          getPowerSystems(powerName, refSystem?.id)
            .then(setAllSystems)
            .catch(() => {})
            .finally(() => setRefreshing(false));
        }, 3000);
      })
      .catch(() => setRefreshing(false));
  }, [powerName, allSystems.length > 0 ? allSystems[0].system_id64 : null]);

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
        reinforcement: sys.reinforcement,
        undermining: sys.undermining,
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
        cp_decay: sys.cp_decay,
        distance_ly: sys.distance_from_center,
        score,
        meritsRemaining,
        meritsNeeded,
        snapshot_time: sys.snapshot_time,
      };
    });
  }, [displaySystems]);

  // Fetch Spansh enrichment data — re-fetches whenever enriched systems change.
  useEffect(() => {
    if (enriched.length === 0) return;
    setEnriching(true);

    const ids = enriched.map(r => r.system_id64);
    getSpanshEnrichmentBatch(ids)
      .then(result => {
        setEnrichment(result);
      })
      .catch(() => {
        // Silently fail — enrichment is a nice-to-have.
        // Do NOT set enrichDone so that the next render can retry.
        console.warn("Spansh enrichment fetch failed, will retry on next render");
      })
      .finally(() => setEnriching(false));
  }, [enriched]);

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

  // ── Admin: cache management ──────────────────────────────────────────────

  async function handleFlushCache() {
    if (!confirm("Clear ALL enrichment cache? Next page load will re-fetch from Spansh.")) return;
    setCaching(true);
    try {
      await clearEnrichmentCache();
      setEnrichment({});
      // Re-trigger enrichment fetch by toggling enriched dependency
      if (enriched.length > 0) {
        const ids = enriched.map(r => r.system_id64);
        const result = await getSpanshEnrichmentBatch(ids, true);
        setEnrichment(result);
      }
    } catch (e) {
      console.error("Flush cache failed:", e);
    } finally {
      setCaching(false);
    }
  }

  async function handleRefreshCache() {
    if (enriched.length === 0) return;
    setCaching(true);
    try {
      const ids = enriched.map(r => r.system_id64);
      const result = await getSpanshEnrichmentBatch(ids, true);
      setEnrichment(result);
    } catch (e) {
      console.error("Refresh cache failed:", e);
    } finally {
      setCaching(false);
    }
  }

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
          and undermining threat (higher net undermining = needs more help). Sort by clicking the column buttons.
        </p>

        {/* Row 1: Power + Ref */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <PowerSelector value={powerName} onChange={handleSetPower} />
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
          <span>📍 Distance: up to 30 pts (30 at 0 LY → 0 at 100 LY)</span>
          <span>⚔ Threat: up to 20 pts (higher net undermining = needs help)</span>
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
          {!enriching && Object.keys(enrichment).length > 0 && (
            <span style={{ marginLeft: 8, color: "#57606a", fontSize: 11 }}>
              ✓ {Object.values(enrichment).filter(e => e.has_platinum || e.has_boom).length} enriched
            </span>
          )}

          {/* Stale refresh status */}
          {refreshing && (
            <span style={{ marginLeft: 8, color: "#FF8C00", fontSize: 11 }}>
              🔄 Refreshing stale data…
            </span>
          )}

          {/* Admin: cache management buttons */}
          {isAdmin && (
            <>
              <button
                onClick={handleFlushCache}
                disabled={caching}
                style={{
                  marginLeft: 8, padding: "3px 8px", fontSize: 10, borderRadius: 3,
                  cursor: caching ? "wait" : "pointer",
                  border: "1px solid #D94A4A", background: "#2d0000",
                  color: caching ? "#666" : "#D94A4A",
                  fontWeight: 600, whiteSpace: "nowrap",
                }}
                title="Delete ALL enrichment cache entries — next load re-fetches from Spansh"
              >
                🗑 Flush
              </button>
              <button
                onClick={handleRefreshCache}
                disabled={caching}
                style={{
                  padding: "3px 8px", fontSize: 10, borderRadius: 3,
                  cursor: caching ? "wait" : "pointer",
                  border: "1px solid #FF8C00", background: "#2d1a00",
                  color: caching ? "#666" : "#FF8C00",
                  fontWeight: 600, whiteSpace: "nowrap",
                }}
                title="Re-fetch enrichment for visible systems from Spansh (ignore cache)"
              >
                🔄 Refresh
              </button>
            </>
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

      {/* ── Pill cards — 3-column grid ──────────────────────────────────── */}
      {sorted.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8,
        }}>
          {sorted.map((row) => {
            const r   = row.reinforcement ?? 0;
            const u   = row.undermining   ?? 0;
            const net = netValue(r, u, row.cp_decay);

            // Background tint by score tier
            const rowBg = row.score >= 100 ? "#2a0000"
                        : row.score >= 80  ? "#1a0000"
                        : row.score >= 60  ? "#150c00"
                        : "#0d1117";

            const enc = enrichment[row.system_id64];
            const hasPlat   = enc?.has_platinum ?? false;
            const hasBoom   = enc?.has_boom ?? false;
            const hasPrist  = enc?.has_pristine ?? false;
            const stale     = isStale(row.snapshot_time);

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
href={`https://inara.cz/elite/starsystem/?search=${encodeURIComponent(row.name)}`}
                    target="_blank" rel="noreferrer"
                    style={{ color: "#58a6ff", textDecoration: "none", fontWeight: 600, fontSize: 13, flex: 1 }}
                  >
                    {row.name}
                  </a>

                  {/* Stale badge */}
                  {stale && <StaleBadge snapshotTime={row.snapshot_time} />}

                  {/* PP State */}
                  <PPBadge state={row.power_state} />

                  {/* PLAT badge */}
                  {hasPlat && <PlatBadge />}

                  {/* BOOM badge */}
                  {hasBoom && <BoomBadge />}

                  {/* PRIST badge */}
                  {hasPrist && <PristBadge />}

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
                  {row.cp_decay != null && row.cp_decay > 0 && (
                    <span style={{ color: CP_DECAY_COLOR }}>
                      Decay: <strong>−{row.cp_decay.toLocaleString()}</strong>
                    </span>
                  )}
                  {(r > 0 || u > 0) && (
                    <span>
                      Net: <strong style={{ color: net >= 0 ? "#4AD94A" : "#D94A4A" }}>
                        {net >= 0 ? "+" : ""}{net.toLocaleString()}
                      </strong>
                    </span>
                  )}
                  {(() => {
                    const toSafety = meritsToSafety(row.power_state, row.control_progress);
                    return toSafety != null ? (
                      <span>
                        To safety: <strong style={{ color: "#FF8C00" }}>{toSafety.toLocaleString()}</strong>
                      </span>
                    ) : null;
                  })()}
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