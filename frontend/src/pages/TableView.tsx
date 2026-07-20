import { useState, useEffect, useMemo, useCallback } from "react";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { getRecommendations, RecommendationsResponse, RecommendationItem } from "../api/recommendations";
import { getContestedSystems, ContestedSystemInfo, parseConflictProgress, formatDataAge, isStale } from "../api/contested";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor, PP_STATE_LABELS } from "../constants/ppColors";
import PowerSelector from "../components/PowerSelector";
import RefSystemSelector from "../components/RefSystemSelector";
import SystemListInput from "../components/SystemListInput";
import RecommendationPanel from "../components/RecommendationPanel";
import { useFilterSettings, FILTER_DEFAULTS } from "../hooks/useFilterSettings";

// ── PP Cycle clock helpers ─────────────────────────────────────────────────
// Cycles reset every Thursday at 07:00 UTC

function getLastCycleReset(): Date {
  const now = new Date();
  // Thursday = day 4 (0=Sun)
  const day = now.getUTCDay();
  const daysSinceThurs = (day + 7 - 4) % 7;
  const resetDate = new Date(Date.UTC(
    now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - daysSinceThurs, 7, 0, 0
  ));
  // If reset is in the future (before 07:00 on Thursday), step back one week
  if (resetDate > now) {
    resetDate.setUTCDate(resetDate.getUTCDate() - 7);
  }
  return resetDate;
}

function getNextCycleReset(): Date {
  const last = getLastCycleReset();
  const next = new Date(last);
  next.setUTCDate(next.getUTCDate() + 7);
  return next;
}

function formatDuration(ms: number): string {
  if (ms <= 0) return "0h";
  const totalSec = Math.floor(ms / 1000);
  const d = Math.floor(totalSec / 86400);
  const h = Math.floor((totalSec % 86400) / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

interface IngestStatus {
  last_run_at: string | null;
  completed_at: string | null;
  status: string | null;
  records_processed: number | null;
  next_run_at: string | null;
}

function useCycleClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  const last  = getLastCycleReset();
  const next  = getNextCycleReset();
  const since = now.getTime() - last.getTime();
  const until = next.getTime() - now.getTime();
  // Days elapsed in cycle (1.0–7.0)
  const daysElapsed = Math.max(1, Math.min(7, since / 86_400_000));
  // Progress through cycle (0–1)
  const cyclePct = Math.min(1, since / (7 * 86_400_000));
  return { since: formatDuration(since), until: formatDuration(until), cyclePct, daysElapsed, nextReset: next };
}

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

function ContestedBadge() {
  return (
    <span style={{
      background: "#2d1f00", color: "#FF8C00", border: "1px solid #FF8C0066",
      borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700,
    }}>
      ⚔ CONTESTED
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

// ── Cycle Clock Banner ─────────────────────────────────────────────────────

function CycleBanner({ ingestStatus }: { ingestStatus: IngestStatus | null }) {
  const { since, until, cyclePct, nextReset } = useCycleClock();

  const statusColor = ingestStatus?.status === "completed" ? "#4AD94A"
                    : ingestStatus?.status === "running"   ? "#4A90D9"
                    : ingestStatus?.status === "failed"    ? "#D94A4A"
                    : "#555";

  const lastRunLabel = ingestStatus?.last_run_at
    ? new Date(ingestStatus.last_run_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : null;
  const nextRunLabel = ingestStatus?.next_run_at
    ? new Date(ingestStatus.next_run_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : null;

  const resetLabel = nextReset.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  // Urgency colour: red in last day, amber in last 2 days, else teal
  const urgencyColor = cyclePct > 6/7 ? "#D94A4A" : cyclePct > 5/7 ? "#D9A84A" : "#00E5CC";

  return (
    <div style={{
      display: "flex", flexWrap: "wrap", gap: 0,
      background: "#0d1117", border: "1px solid #21262d", borderRadius: 8,
      marginBottom: 12, overflow: "hidden", fontSize: 12,
    }}>
      {/* Cycle progress bar */}
      <div style={{ width: "100%", height: 3, background: "#21262d" }}>
        <div style={{ height: "100%", width: `${cyclePct * 100}%`, background: urgencyColor, transition: "width 1s" }} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 0, width: "100%" }}>
        {/* Since reset */}
        <div style={{ padding: "8px 16px", borderRight: "1px solid #21262d", display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: 10, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.05em" }}>Since Reset</span>
          <span style={{ color: "#e6edf3", fontWeight: 700, fontSize: 14 }}>{since}</span>
        </div>

        {/* Until next reset */}
        <div style={{ padding: "8px 16px", borderRight: "1px solid #21262d", display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: 10, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.05em" }}>Next Reset</span>
          <span style={{ color: urgencyColor, fontWeight: 700, fontSize: 14 }}>{until}</span>
          <span style={{ fontSize: 10, color: "#444" }}>{resetLabel}</span>
        </div>

        {/* Spansh data status */}
        <div style={{ padding: "8px 16px", borderRight: "1px solid #21262d", display: "flex", flexDirection: "column", gap: 2, flex: 1, minWidth: 200 }}>
          <span style={{ fontSize: 10, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.05em" }}>Spansh Data</span>
          {lastRunLabel ? (
            <>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor, display: "inline-block", flexShrink: 0 }} />
                <span style={{ color: statusColor, fontWeight: 700, textTransform: "capitalize" }}>
                  {ingestStatus?.status ?? "unknown"}
                </span>
                {ingestStatus?.records_processed != null && (
                  <span style={{ color: "#57606a" }}>· {ingestStatus.records_processed.toLocaleString()} records</span>
                )}
              </span>
              <span style={{ fontSize: 10, color: "#444" }}>Last: {lastRunLabel}</span>
            </>
          ) : (
            <span style={{ color: "#555" }}>No ingest data yet</span>
          )}
          {nextRunLabel && (
            <span style={{ fontSize: 10, color: "#444" }}>Next: {nextRunLabel}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function TableView() {
  const { powerName, refSystem, systemList, setPower, setRef, setSystemList } = useSelectionState();

  const [systems,           setSystems]           = useState<PPSystemEntry[]>([]);
  const [recommendations,   setRecommendations]   = useState<RecommendationsResponse | null>(null);
  const [contestedSystems,  setContestedSystems]  = useState<ContestedSystemInfo[]>([]);
  const [loadingSystems,    setLoadingSystems]    = useState(false);
  const [loadingRecos,      setLoadingRecos]      = useState(false);
  const [loadingContested,  setLoadingContested]  = useState(false);
  const [error,             setError]             = useState<string | null>(null);
  const [sortKey,           setSortKey]           = useState<string>("control_progress");
  const [sortDir,           setSortDir]           = useState<SortDir>("asc");

  // Centralised filter settings with optional cookie persistence
  const { settings, saveEnabled, setSaveEnabled, set: setFilter } = useFilterSettings();
  const { expandMinProgress, contestedMaxGap } = settings;

  // Spansh ingest status (public endpoint, no auth)
  const [ingestStatus,      setIngestStatus]      = useState<IngestStatus | null>(null);
  const fetchIngestStatus = useCallback(() => {
    fetch("/api/admin/ingest-status")
      .then(r => r.ok ? r.json() as Promise<IngestStatus> : Promise.reject())
      .then(setIngestStatus)
      .catch(() => {});
  }, []);
  useEffect(() => {
    fetchIngestStatus();
    const id = setInterval(fetchIngestStatus, 5 * 60_000);  // refresh every 5 min
    return () => clearInterval(id);
  }, [fetchIngestStatus]);

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
    getPowerSystems(powerName, refSystem?.id)
      .then(setSystems)
      .catch(e => setError(String(e)))
      .finally(() => setLoadingSystems(false));
  }, [powerName, refSystem?.id]);

  useEffect(() => {
    if (!powerName) { setRecommendations(null); return; }
    setLoadingRecos(true);
    getRecommendations(powerName, refSystem?.id)
      .then(setRecommendations)
      .catch(() => setRecommendations(null))
      .finally(() => setLoadingRecos(false));
  }, [powerName, refSystem?.id]);

  // Fetch contested systems — direct endpoint: power_state='Contested' near our territory
  useEffect(() => {
    if (!powerName) { setContestedSystems([]); return; }
    setLoadingContested(true);
    getContestedSystems(powerName)
      .then(setContestedSystems)
      .catch(() => setContestedSystems([]))
      .finally(() => setLoadingContested(false));
  }, [powerName]);

  // Default sort: by control_progress ascending (most at-risk first) when no ref;
  // by distance ascending when a reference system is selected.
  useEffect(() => {
    setSortKey(refSystem ? "distance_from_center" : "control_progress");
    setSortDir("asc");
  }, [refSystem?.id]);

  function handleSort(col: string) {
    if (col === sortKey) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(col); setSortDir("asc"); }
  }

  // Apply system list filter if active
  const displaySystems = useMemo(() => {
    if (systemList.length === 0) return systems;
    const nameSet = new Set(systemList.map(n => n.toLowerCase()));
    return systems.filter(s => nameSet.has(s.name.toLowerCase()));
  }, [systems, systemList]);

  const sorted = useMemo(() => {
    return [...displaySystems].sort((a, b) => {
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

  const showDist = !!refSystem;

  // Helper: parse conflict_progress JSON string on a RecommendationItem (same format
  // as ContestedSystemInfo.conflict_progress)
  function parseExpandConflict(item: { conflict_progress: string | null }): Array<{ power: string; progress: number }> {
    if (!item.conflict_progress) return [];
    try { return JSON.parse(item.conflict_progress); } catch { return []; }
  }

  // Client-side filter + sort for expand targets.
  //
  // Filter:  hide systems where NO power has reached expandMinProgress %.
  //          progress is 0–1+ where 1.0 = 120k merits (same scale as Contested).
  //          0% = show all.
  //
  // Sort:    1. max(power progress) DESC — highest lead progress first
  //          2. sum(all power progress) DESC — most total activity as tiebreak
  //
  // Ranking score shown in pill = round(maxProgress * 100) to nearest integer.
  const filteredRecommendations = useMemo<RecommendationsResponse | null>(() => {
    if (!recommendations) return null;

    const filtered = recommendations.expand.filter(item => {
      if (expandMinProgress <= 0) return true;
      const entries = parseExpandConflict(item);
      const maxProg = entries.length > 0
        ? Math.max(...entries.map(e => e.progress))
        : (item.control_progress ?? 0);
      return maxProg * 100 >= expandMinProgress;
    });

    const sorted = [...filtered].sort((a, b) => {
      const ea = parseExpandConflict(a);
      const eb = parseExpandConflict(b);
      const maxA = ea.length > 0 ? Math.max(...ea.map(e => e.progress)) : (a.control_progress ?? 0);
      const maxB = eb.length > 0 ? Math.max(...eb.map(e => e.progress)) : (b.control_progress ?? 0);
      if (maxB !== maxA) return maxB - maxA;                                    // highest lead first
      const sumA = ea.reduce((s, e) => s + e.progress, 0) || (a.control_progress ?? 0);
      const sumB = eb.reduce((s, e) => s + e.progress, 0) || (b.control_progress ?? 0);
      return sumB - sumA;                                                        // most total activity
    });

    return { ...recommendations, expand: sorted };
  }, [recommendations, expandMinProgress]);

  // Client-side filter for contested systems
  const filteredContested = useMemo<ContestedSystemInfo[]>(() => {
    return contestedSystems.filter(item => {
      const entries = parseConflictProgress(item);

      // ── Acquisition gate: at least one power must be at ≥ 100% (≥ 120k merits) ──
      // progress is normalised 0–1+ where 1.0 = 120k acquisition threshold.
      // Systems where nobody has crossed the line yet are noise — hide them.
      const maxProgress = entries.length > 0
        ? Math.max(...entries.map(e => e.progress))
        : (item.control_progress ?? 0);
      if (maxProgress < 1.0) return false;

      // ── Selected-power gate: our power must be present in conflict_progress ──
      // powerName is the currently selected power; if not set, keep all.
      if (powerName) {
        const present = entries.some(e => e.power === powerName);
        if (!present) return false;
      }

      // ── Max-gap filter: top power must not lead next by more than N % ──
      if (contestedMaxGap < 100) {
        if (entries.length < 2) return true;  // can't compute gap — keep it
        const ranked = [...entries].sort((a, b) => b.progress - a.progress);
        const gapPct = (ranked[0].progress - ranked[1].progress) * 100;
        if (gapPct > contestedMaxGap) return false;
      }

      return true;
    });
  }, [contestedSystems, contestedMaxGap, powerName]);

  return (
    <div style={{
      padding: "16px 20px", background: "#0d1117", minHeight: "calc(100vh - 44px)",
      fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3",
    }}>
      {/* ── Cycle clock + Spansh status banner ── */}
      <CycleBanner ingestStatus={ingestStatus} />

      {/* Controls */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <PowerSelector value={powerName} onChange={setPower} />
        <RefSystemSelector value={refSystem} onChange={setRef} />
        <SystemListInput value={systemList} onChange={setSystemList} powerName={powerName} />
        {loadingSystems && <span style={{ fontSize: 13, color: "#8b949e" }}>Loading systems…</span>}
        {error && <span style={{ fontSize: 13, color: "#D94A4A" }}>{error}</span>}
        {systems.length > 0 && !loadingSystems && (
          <span style={{ fontSize: 12, color: "#8b949e", marginLeft: "auto" }}>
            {systemList.length > 0
              ? `${displaySystems.length} of ${systems.length} systems (filtered)`
              : `${systems.length} system${systems.length !== 1 ? "s" : ""}`}
            {powerName && ` · ${powerName}`}
            {refSystem && ` · ref: ${refSystem.name}`}
            {contestedSystems.length > 0 && (
              <span style={{ marginLeft: 8, color: "#FF8C00", fontWeight: 700 }}>
                · {contestedSystems.length} ⚔ contested
              </span>
            )}
          </span>
        )}
      </div>

      {/* ── Expand Filters bar — min lead progress ─────────────────────────── */}
      {(recommendations?.expand.length ?? 0) > 0 && (
        <div style={{
          display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center",
          background: "#0d2a4a22", border: "1px solid #1f6feb33", borderRadius: 6,
          padding: "8px 14px", marginBottom: 6, fontSize: 12,
        }}>
          <span style={{ color: "#4A90D9", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", flexShrink: 0 }}>
            Expand Filters
          </span>

          {/* Min lead-progress slider: hides systems where no power has reached N% */}
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#8b949e" }}>
            <span
              style={{ color: "#4A90D9", fontWeight: 600, whiteSpace: "nowrap", cursor: "help", borderBottom: "1px dashed #4A90D966" }}
              title={
                "Hides expansion targets where no power has yet reached N% of the 120,000-merit acquisition threshold.\n" +
                "Example: 25% shows only systems where at least one power has ≥ 30,000 merits.\n" +
                "0% = show all. Systems are always sorted: highest lead % first, then highest combined total."
              }
            >
              ⚡ Min lead progress ≥
            </span>
            <input
              type="range" min={0} max={100} step={5}
              value={expandMinProgress}
              onChange={e => setFilter("expandMinProgress", Number(e.target.value))}
              style={{ accentColor: "#4A90D9", width: 140 }}
            />
            <input
              type="number" min={0} max={100} step={1}
              value={expandMinProgress}
              onChange={e => setFilter("expandMinProgress", Math.max(0, Math.min(100, Number(e.target.value))))}
              style={{
                width: 48, background: "#161b22", border: "1px solid #30363d", borderRadius: 4,
                color: "#e6edf3", fontSize: 12, padding: "2px 5px", fontVariantNumeric: "tabular-nums",
              }}
            />
            <span style={{ color: expandMinProgress === 0 ? "#57606a" : "#4A90D9", fontWeight: 700 }}>
              {expandMinProgress === 0 ? "ALL" : `≥ ${expandMinProgress}%`}
            </span>
          </label>

          <span style={{ color: "#57606a", fontSize: 11, marginLeft: "auto" }}>
            {filteredRecommendations?.expand.length ?? 0} / {recommendations!.expand.length} shown
          </span>
        </div>
      )}

      {/* Contested gap filter (only shown when contested data is present) */}
      {(contestedSystems.length > 0 || loadingContested) && (
        <div style={{
          display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center",
          background: "#1a100022", border: "1px solid #FF8C0033", borderRadius: 6,
          padding: "8px 14px", marginBottom: 6, fontSize: 12,
        }}>
          <span style={{ color: "#FF8C00", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", flexShrink: 0 }}>
            Contested Filters
          </span>

          {/* Max gap slider */}
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#8b949e" }}>
            <span
              style={{ color: "#FF8C00", fontWeight: 600, whiteSpace: "nowrap", cursor: "help", borderBottom: "1px dashed #FF8C0066" }}
              title={
                "Hides contested systems where the leading power is more than N% ahead of the second-placed power.\n" +
                "Example: setting 15% means only show systems where the gap between 1st and 2nd place is ≤ 15%.\n" +
                "Lower values = more evenly-matched contests where your intervention could change the outcome.\n" +
                "100% = show all contested systems."
              }
            >
              ⚔ Max lead gap ≤
            </span>
            <input
              type="range" min={0} max={100} step={5}
              value={contestedMaxGap}
              onChange={e => setFilter("contestedMaxGap", Number(e.target.value))}
              style={{ accentColor: "#FF8C00", width: 120 }}
            />
            <input
              type="number" min={0} max={100} step={1}
              value={contestedMaxGap}
              onChange={e => setFilter("contestedMaxGap", Math.max(0, Math.min(100, Number(e.target.value))))}
              style={{
                width: 48, background: "#161b22", border: "1px solid #30363d", borderRadius: 4,
                color: "#e6edf3", fontSize: 12, padding: "2px 5px", fontVariantNumeric: "tabular-nums",
              }}
            />
            <span style={{ color: "#e6edf3", fontWeight: 700 }}>
              {contestedMaxGap >= 100 ? "ALL" : `${contestedMaxGap}%`}
            </span>
          </label>

          <span style={{ color: "#57606a", fontSize: 11, marginLeft: "auto" }}>
            {filteredContested.length} / {contestedSystems.length} contested shown
          </span>
        </div>
      )}

      {/* Cookie persistence checkbox — shown whenever any filter bar is visible */}
      {((recommendations?.expand.length ?? 0) > 0 || contestedSystems.length > 0) && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "4px 14px", marginBottom: 10, fontSize: 12,
        }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "#8b949e", userSelect: "none" }}>
            <input
              type="checkbox"
              checked={saveEnabled}
              onChange={e => setSaveEnabled(e.target.checked)}
              style={{ accentColor: "#4A90D9", width: 14, height: 14 }}
            />
            <span>Remember filter settings in this browser</span>
          </label>
          {saveEnabled && (
            <span style={{ color: "#57606a", fontSize: 11 }}>
              ✓ Settings are saved (cookie expires in 365 days)
            </span>
          )}
          {!saveEnabled && (
            <span style={{ color: "#57606a", fontSize: 11 }}>
              Defaults loaded — check the box to persist your settings
            </span>
          )}
          {/* Reset to defaults */}
          <button
            onClick={() => {
              Object.entries(FILTER_DEFAULTS).forEach(([k, v]) =>
                setFilter(k as keyof typeof FILTER_DEFAULTS, v as never)
              );
            }}
            style={{
              marginLeft: 12, background: "none", border: "1px solid #30363d", borderRadius: 4,
              color: "#8b949e", fontSize: 11, padding: "2px 8px", cursor: "pointer",
            }}
          >
            Reset to defaults
          </button>
        </div>
      )}

      {/* Recommendation panel — includes Contested section */}
      <RecommendationPanel
        recommendations={filteredRecommendations}
        loading={loadingRecos}
        contested={filteredContested}
        loadingContested={loadingContested}
      />

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
      {powerName && !loadingSystems && systems.length > 0 && displaySystems.length === 0 && systemList.length > 0 && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 8 }}>
          None of the {systemList.length} system{systemList.length !== 1 ? "s" : ""} in your list were found under {powerName}. Check names or clear the filter.
        </p>
      )}

      {/* Table */}
      {displaySystems.length > 0 && (
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
                // Highlight if in system list
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

      {/* ── Contested Systems section ──────────────────────────────────────── */}
      {powerName && (contestedSystems.length > 0 || loadingContested) && (
        <div style={{ marginTop: 20 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 8,
            borderBottom: "2px solid #FF8C0033", paddingBottom: 6,
          }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "#FF8C00" }}>
              ⚔ Contested Systems
            </h3>
            <span style={{ fontSize: 12, color: "#8b949e" }}>
              Systems currently in Contested state — sorted by proximity to {powerName}
            </span>
            {loadingContested && <span style={{ fontSize: 12, color: "#555" }}>Loading…</span>}
            {!loadingContested && filteredContested.length < contestedSystems.length && (
              <span style={{ fontSize: 12, color: "#FF8C00" }}>
                {filteredContested.length} of {contestedSystems.length} shown (gap filter active)
              </span>
            )}
          </div>

          {filteredContested.length > 0 && (
            <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid #FF8C0033" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr>
                    {["System", "Owner", "State", "Progress", "Reinf.", "Underm.", "Net R–U", "Dist LY", "Data Age"].map(h => (
                      <th key={h} style={{
                        padding: "8px 10px", textAlign: "left", fontSize: 11, fontWeight: 700,
                        color: "#FF8C00", textTransform: "uppercase", letterSpacing: "0.05em",
                        background: "#1a1000", borderBottom: "2px solid #FF8C0033",
                        whiteSpace: "nowrap",
                      }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredContested.slice(0, 30).map((item, i) => {
                    const r   = item.reinforcement ?? 0;
                    const u   = item.undermining   ?? 0;
                    const net = r - u;
                    const stale = isStale(item.spansh_updated_at);
                    const rowBg = stale
                      ? (i % 2 === 0 ? "#1a1200" : "#201500")   // amber tint for stale
                      : (i % 2 === 0 ? "#120d00" : "#1a1200");
                    return (
                      <tr key={item.system_id64} style={{ background: rowBg }}>
                        {/* System name */}
                        <td style={{ padding: "7px 10px", whiteSpace: "nowrap" }}>
                          <a
                            href={`https://www.edsm.net/en/system/id/-/name/${encodeURIComponent(item.system_name)}`}
                            target="_blank" rel="noreferrer"
                            style={{ color: "#FF8C00", textDecoration: "none", fontWeight: 500 }}
                          >
                            {item.system_name}
                          </a>
                          {" "}
                          <ContestedBadge />
                        </td>
                        {/* Owner */}
                        <td style={{ padding: "7px 10px", color: "#8b949e", fontSize: 12, whiteSpace: "nowrap" }}>
                          {item.controlling_power}
                        </td>
                        {/* State */}
                        <td style={{ padding: "7px 10px" }}>
                          {item.power_state
                            ? <span style={{ background: ppStateColor(item.power_state), color: "#fff", borderRadius: 4, padding: "2px 6px", fontSize: 11, fontWeight: 600 }}>
                                {PP_STATE_LABELS[item.power_state] ?? item.power_state}
                              </span>
                            : <span style={{ color: "#555" }}>—</span>}
                        </td>
                        {/* Progress */}
                        <td style={{ padding: "7px 10px" }}>
                          {item.control_progress != null ? (
                            <div style={{ minWidth: 60 }}>
                              <div style={{ fontSize: 11, color: item.control_progress <= 0.2 ? "#FF4444" : item.control_progress <= 0.5 ? "#FF8C00" : "#D9A84A", fontWeight: 600, textAlign: "right" }}>
                                {(item.control_progress * 100).toFixed(1)}%
                              </div>
                              <div style={{ height: 3, borderRadius: 2, background: "#2a2a3a" }}>
                                <div style={{ height: "100%", width: `${Math.min(100, item.control_progress * 100)}%`, background: "#FF8C00", borderRadius: 2 }} />
                              </div>
                            </div>
                          ) : <span style={{ color: "#555" }}>—</span>}
                        </td>
                        {/* Reinforcement */}
                        <td style={{ padding: "7px 10px", textAlign: "right", color: "#4AD94A", fontVariantNumeric: "tabular-nums" }}>
                          {r > 0 ? r.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                        </td>
                        {/* Undermining */}
                        <td style={{ padding: "7px 10px", textAlign: "right", color: u > r ? "#D94A4A" : u > 0 ? "#D9A84A" : "#555", fontVariantNumeric: "tabular-nums" }}>
                          {u > 0 ? u.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                        </td>
                        {/* Net R–U (enemy perspective: negative = we're winning) */}
                        <td style={{ padding: "7px 10px", textAlign: "right", color: net < 0 ? "#4AD94A" : net > 0 ? "#D94A4A" : "#555", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                          {(r > 0 || u > 0) ? `${net >= 0 ? "+" : ""}${net.toLocaleString()}` : <span style={{ color: "#555" }}>—</span>}
                        </td>
                        {/* Distance */}
                        <td style={{ padding: "7px 10px", textAlign: "right", color: item.distance_from_power != null && item.distance_from_power <= 10 ? "#FF8C00" : "#8b949e" }}>
                          {item.distance_from_power != null ? `${item.distance_from_power.toFixed(1)}` : "—"}
                        </td>
                        {/* Data age — stale = amber warning */}
                        <td style={{ padding: "7px 10px", textAlign: "right", whiteSpace: "nowrap" }}
                            title={item.spansh_updated_at ? `Spansh last updated: ${item.spansh_updated_at} UTC` : "No update timestamp"}>
                          {stale
                            ? <span style={{ color: "#D9A84A", fontWeight: 700 }}>⚠ {formatDataAge(item.spansh_updated_at)}</span>
                            : <span style={{ color: "#57606a" }}>{formatDataAge(item.spansh_updated_at)}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
