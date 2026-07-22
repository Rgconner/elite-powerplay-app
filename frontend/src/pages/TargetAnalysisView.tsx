import { useState, useEffect, useMemo, useCallback, type CSSProperties } from "react";
import { getTargetAnalysis, TargetAnalysisItem } from "../api/targeting";
import { netValue } from "../utils/decay";
import { listPowers } from "../api/powers";
import { ppStateColor, PP_STATE_LABELS, powerColor } from "../constants/ppColors";

// ── Types ─────────────────────────────────────────────────────────────────

type SortDir = "asc" | "desc";

// ── Band constants (same as backend) ─────────────────────────────────────
// Used to display "≈ N merits" labels next to progress threshold sliders
const BAND_EXPLOITED  = 213_000;  // 333k − 120k
const BAND_FORTIFIED  = 334_000;  // 667k − 333k
const BAND_STRONGHOLD = 334_000;  // proxy
const MERIT_ACQUIRE   = 120_000;
const MERIT_FORTIFIED = 333_000;
const MERIT_STRONGHOLD= 667_000;

/** Absolute merit position given progress in a state */
function meritPos(state: string | null, progress: number): number {
  const lower = state === "Stronghold" ? MERIT_STRONGHOLD
              : state === "Fortified"  ? MERIT_FORTIFIED
              : MERIT_ACQUIRE;
  const band  = state === "Stronghold" ? BAND_STRONGHOLD
              : state === "Fortified"  ? BAND_FORTIFIED
              : BAND_EXPLOITED;
  return Math.round(lower + progress * band);
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

// ── Sub-components ─────────────────────────────────────────────────────────

function PPBadge({ state }: { state: string | null }) {
  if (!state) return <span style={{ color: "#555" }}>—</span>;
  return (
    <span style={{
      background: ppStateColor(state), color: "#fff",
      borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600,
    }}>
      {PP_STATE_LABELS[state] ?? state}
    </span>
  );
}

function ContestedBadge() {
  return (
    <span style={{
      background: "#2d1f00", color: "#FF8C00", border: "1px solid #FF8C0066",
      borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 700,
      letterSpacing: "0.04em",
    }}>
      ⚔ CONTESTED
    </span>
  );
}

/** Urgency band for a target — inverted from fortify: high score = high threat TO enemy. */
function ThreatBand({ score }: { score: number }) {
  let label: string, bg: string, fg: string;
  if (score >= 1200)      { label = "PRIME";    bg = "#3d0000"; fg = "#FF4444"; }
  else if (score >= 900)  { label = "HIGH";     bg = "#3d1a00"; fg = "#FF8C00"; }
  else if (score >= 600)  { label = "MEDIUM";   bg = "#2a2000"; fg = "#D9A84A"; }
  else if (score >= 350)  { label = "LOW";      bg = "#1a1a2e"; fg = "#8899AA"; }
  else                    { label = "MINIMAL";  bg = "#161b22"; fg = "#555566"; }
  return (
    <span style={{
      background: bg, color: fg, border: `1px solid ${fg}66`,
      borderRadius: 3, padding: "1px 7px", fontSize: 10, fontWeight: 800,
      letterSpacing: "0.05em",
    }}>
      {label}
    </span>
  );
}

/** Progress bar — coloured by threshold proximity.
 *  thresholds: { critical, high, medium } as 0.0–1.0 fractions
 */
function ProgressBar({
  value, thresholds,
}: {
  value: number | null;
  thresholds: { critical: number; high: number; medium: number };
}) {
  if (value == null) return <span style={{ color: "#555" }}>—</span>;
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = value <= 0              ? "#FF4444"
              : value <= thresholds.critical ? "#FF4444"
              : value <= thresholds.high     ? "#FF8C00"
              : value <= thresholds.medium   ? "#D9A84A"
              : value < 1.0                  ? "#4AD94A"
              : "#00E5CC";
  return (
    <div style={{ minWidth: 70 }}>
      <div style={{ fontSize: 11, color, fontWeight: 600, textAlign: "right", marginBottom: 1 }}>
        {(value * 100).toFixed(1)}%
        {value <= 0 && <span title="Already at downgrade threshold"> !</span>}
      </div>
      <div style={{ height: 3, borderRadius: 2, background: "#2a2a3a", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function DaysCell({ days }: { days: number | null | undefined }) {
  if (days == null) return <span style={{ color: "#555" }}>—</span>;
  if (days === 0) return <span style={{ color: "#FF4444", fontWeight: 800 }}>NOW ✓</span>;
  const color = days < 2 ? "#FF4444" : days < 5 ? "#FF8C00" : "#D9A84A";
  return <span style={{ color, fontWeight: 600 }}>{days.toFixed(1)}d</span>;
}

function TrendArrow({ trend }: { trend: string }) {
  // For enemy systems: worsening (for them) = good for us
  if (trend === "worsening") return <span style={{ color: "#4AD94A", fontSize: 14 }} title="Enemy progress falling — good target">↘</span>;
  if (trend === "improving") return <span style={{ color: "#D94A4A", fontSize: 14 }} title="Enemy progress rising — reinforcing">↗</span>;
  return <span style={{ color: "#444" }}>—</span>;
}

function Th({ col, label, sortKey, sortDir, onSort, width, title }: {
  col: string; label: string; sortKey: string; sortDir: SortDir;
  onSort: (k: string) => void; width?: number; title?: string;
}) {
  const active = col === sortKey;
  return (
    <th onClick={() => onSort(col)} title={title} style={{
      padding: "10px 10px", textAlign: "left", fontSize: 11, fontWeight: 700,
      color: active ? "#e6edf3" : "#8b949e", textTransform: "uppercase",
      letterSpacing: "0.05em", cursor: "pointer", whiteSpace: "nowrap",
      background: "#161b22", borderBottom: "2px solid #30363d", width,
      userSelect: "none",
    }}>
      {label}
      <span style={{ marginLeft: 3, opacity: active ? 1 : 0.3 }}>
        {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
      </span>
    </th>
  );
}

// ── Power multi-select ─────────────────────────────────────────────────────

function PowerMultiSelect({
  label, value, onChange, allPowers, exclude,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  allPowers: string[];
  exclude: string[];
}) {
  const available = allPowers.filter(p => !exclude.includes(p));

  function toggle(p: string) {
    onChange(value.includes(p) ? value.filter(x => x !== p) : [...value, p]);
  }
  function selectAll() { onChange(available); }
  function clear()     { onChange([]); }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: "#8b949e", fontWeight: 600 }}>{label}</span>
        <button onClick={selectAll} style={smallBtnStyle}>All</button>
        <button onClick={clear}     style={smallBtnStyle}>None</button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        {available.map(p => {
          const sel = value.includes(p);
          const pc  = powerColor(p);
          return (
            <button
              key={p}
              onClick={() => toggle(p)}
              style={{
                padding: "3px 10px", fontSize: 12, borderRadius: 4, cursor: "pointer",
                border: sel ? `1px solid ${pc}` : "1px solid #30363d",
                background: sel ? `${pc}22` : "#161b22",
                color: sel ? pc : "#8b949e",
                fontWeight: sel ? 700 : 400,
                transition: "all 0.1s",
              }}
            >
              {p}
            </button>
          );
        })}
        {available.length === 0 && (
          <span style={{ fontSize: 12, color: "#555" }}>No data yet — run ingest first</span>
        )}
      </div>
    </div>
  );
}

const smallBtnStyle: CSSProperties = {
  padding: "2px 8px", fontSize: 11, borderRadius: 3, cursor: "pointer",
  border: "1px solid #30363d", background: "#161b22", color: "#8b949e",
};

// ── Threshold slider row ───────────────────────────────────────────────────

function ThresholdSlider({
  label, color, value, onChange, min = 1, max = 100, defaultValue,
}: {
  label: string; color: string;
  value: number; onChange: (n: number) => void;
  min?: number; max?: number; defaultValue: number;
}) {
  const changed = value !== defaultValue;
  // Show absolute merit equivalents across states for context
  const exploitedMerit = meritPos("Exploited",  value / 100);
  const fortifiedMerit = meritPos("Fortified",  value / 100);
  const strongholdMerit= meritPos("Stronghold", value / 100);

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
          <label style={{ fontSize: 12, color: changed ? "#e6edf3" : "#8b949e", fontWeight: changed ? 600 : 400 }}>
            {label}
          </label>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {changed && (
            <button
              onClick={() => onChange(defaultValue)}
              style={{ ...smallBtnStyle, fontSize: 10 }}
            >
              reset ({defaultValue}%)
            </button>
          )}
          <input
            type="number" min={min} max={max} step={1}
            value={value}
            onChange={e => { const n = parseInt(e.target.value, 10); if (!isNaN(n) && n >= min && n <= max) onChange(n); }}
            style={{
              width: 52, padding: "3px 6px", fontSize: 13, fontWeight: 600,
              background: "#0d1117", color: changed ? color : "#8b949e",
              border: `1px solid ${changed ? color : "#30363d"}`,
              borderRadius: 4, textAlign: "right", outline: "none",
            }}
          />
          <span style={{ fontSize: 11, color: "#555" }}>%</span>
        </div>
      </div>
      <input
        type="range" min={min} max={max} step={1}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: changed ? color : "#444" }}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
        <span style={{ fontSize: 10, color: "#555" }}>
          ≈ Exploited: {exploitedMerit.toLocaleString()} merits
        </span>
        <span style={{ fontSize: 10, color: "#555" }}>
          · Fortified: {fortifiedMerit.toLocaleString()} merits
        </span>
        <span style={{ fontSize: 10, color: "#555" }}>
          · Stronghold: {strongholdMerit.toLocaleString()} merits
        </span>
      </div>
    </div>
  );
}

// ── Default local thresholds (match backend DEFAULTS) ─────────────────────
const DEFAULT_THRESHOLDS = { critical: 10, high: 25, medium: 50 };

// ── Main component ─────────────────────────────────────────────────────────

export default function TargetAnalysisView() {
  const [allPowers,      setAllPowers]      = useState<string[]>([]);
  const [attackerPower,  setAttackerPower]  = useState<string>("");
  const [targetPowers,   setTargetPowers]   = useState<string[]>([]);
  const [results,        setResults]        = useState<TargetAnalysisItem[]>([]);
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState<string | null>(null);
  const [sortKey,        setSortKey]        = useState<string>("control_progress");
  const [sortDir,        setSortDir]        = useState<SortDir>("asc");
  const [filterPower,    setFilterPower]    = useState<string>("all");

  // ── Local settings ────────────────────────────────────────────────────────
  // These mirror backend defaults; changing them re-runs the analysis to apply.
  // They're sent to the backend as part of the analysis, but since the backend
  // uses admin_settings, we show the *backend-returned* thresholds after a run
  // and allow local override for quick visual filtering without a DB round-trip.
  const [maxTargets,     setMaxTargets]     = useState<number>(50);
  const [thresholds,     setThresholds]     = useState(DEFAULT_THRESHOLDS);
  // After a successful run, backend returns its active thresholds — use those
  // as the "live" reference for progress bar colouring
  const [liveThresholds, setLiveThresholds] = useState(DEFAULT_THRESHOLDS);
  const [showThresholds, setShowThresholds] = useState(false);

  // Load power list on mount
  useEffect(() => {
    listPowers()
      .then(setAllPowers)
      .catch(() => setAllPowers([]));
  }, []);

  const runAnalysis = useCallback(() => {
    if (!attackerPower || targetPowers.length === 0) return;
    setLoading(true);
    setError(null);
    setResults([]);
    getTargetAnalysis(attackerPower, targetPowers)
      .then(r => {
        // Slice client-side by maxTargets (backend uses its own DB setting;
        // this gives immediate feedback without a re-query)
        setResults(r.targets.slice(0, maxTargets));
        // Adopt backend thresholds as live reference
        if (r.progress_thresholds) {
          const t = r.progress_thresholds;
          const live = {
            critical: Math.round(t.critical * 100),
            high:     Math.round(t.high     * 100),
            medium:   Math.round(t.medium   * 100),
          };
          setLiveThresholds(live);
          setThresholds(live);
        }
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [attackerPower, targetPowers, maxTargets]);

  function handleSort(col: string) {
    if (col === sortKey) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(col); setSortDir(col === "score" ? "desc" : "asc"); }
  }

  // Build active thresholds as 0–1 fractions for ProgressBar
  const activeThr = useMemo(() => ({
    critical: thresholds.critical / 100,
    high:     thresholds.high     / 100,
    medium:   thresholds.medium   / 100,
  }), [thresholds]);

  // Filter by target power
  const filtered = useMemo(() =>
    filterPower === "all" ? results : results.filter(r => (r.controlling_power ?? "Unknown") === filterPower),
    [results, filterPower]
  );

  // Additional client-side progress filter using local threshold sliders
  // (allows user to quickly narrow results without re-querying)
  const [progressFilter, setProgressFilter] = useState<"all"|"critical"|"high"|"medium">("all");
  const filteredByProgress = useMemo(() => {
    if (progressFilter === "all") return filtered;
    return filtered.filter(item => {
      const p = item.control_progress ?? 1;
      if (progressFilter === "critical") return p <= activeThr.critical;
      if (progressFilter === "high")     return p <= activeThr.high;
      if (progressFilter === "medium")   return p <= activeThr.medium;
      return true;
    });
  }, [filtered, progressFilter, activeThr]);

  // Sort
  const sorted = useMemo(() => [...filteredByProgress].sort((a, b) => {
    if (sortKey === "net") {
      const na = netValue(a.reinforcement, a.undermining, a.cp_decay);
      const nb = netValue(b.reinforcement, b.undermining, b.cp_decay);
      return cmp(na, nb, sortDir);
    }
    return cmp(
      (a as unknown as Record<string, unknown>)[sortKey],
      (b as unknown as Record<string, unknown>)[sortKey],
      sortDir,
    );
  }), [filteredByProgress, sortKey, sortDir]);

  // Counts per power for filter tabs
  const countsByPower = useMemo(() => {
    const m: Record<string, number> = {};
    results.forEach(r => {
      const key = r.controlling_power ?? "Unknown";
      m[key] = (m[key] ?? 0) + 1;
    });
    return m;
  }, [results]);

  const primeCount     = results.filter(r => r.score >= 1200).length;
  const contestedCount = results.filter(r => r.contested).length;

  return (
    <div style={{
      padding: "16px 20px", background: "#0d1117", minHeight: "calc(100vh - 44px)",
      fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3",
    }}>

      {/* ── Top settings bar: Max Targets + Threshold toggle ─────────────── */}
      <div style={{
        background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
        padding: "10px 14px", marginBottom: 10,
        display: "flex", alignItems: "center", flexWrap: "wrap", gap: 16,
      }}>
        {/* Max targets */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#8b949e", fontWeight: 600, whiteSpace: "nowrap" }}>
            Max targets shown:
          </span>
          <input
            type="range" min={5} max={200} step={5}
            value={maxTargets}
            onChange={e => setMaxTargets(Number(e.target.value))}
            style={{ width: 120, accentColor: "#58a6ff" }}
          />
          <input
            type="number" min={1} max={500} step={1}
            value={maxTargets}
            onChange={e => {
              const n = parseInt(e.target.value, 10);
              if (!isNaN(n) && n >= 1) setMaxTargets(n);
            }}
            style={{
              width: 56, padding: "3px 6px", fontSize: 13, fontWeight: 600,
              background: "#0d1117", color: "#58a6ff", border: "1px solid #30363d",
              borderRadius: 4, textAlign: "right", outline: "none",
            }}
          />
          <span style={{ fontSize: 11, color: "#555" }}>systems</span>
        </div>

        {/* Threshold toggle */}
        <button
          onClick={() => setShowThresholds(v => !v)}
          style={{
            padding: "4px 12px", fontSize: 12, borderRadius: 4, cursor: "pointer",
            border: `1px solid ${showThresholds ? "#FF8C00" : "#30363d"}`,
            background: showThresholds ? "#3d1a00" : "#0d1117",
            color: showThresholds ? "#FF8C00" : "#8b949e",
            fontWeight: 600,
          }}
        >
          {showThresholds ? "▲ Hide" : "▼ Show"} Vulnerability Thresholds
        </button>

        {/* Progress filter quick-buttons */}
        {results.length > 0 && (
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "#555" }}>Show:</span>
            {([
              { key: "all",      label: "All",              color: "#8b949e" },
              { key: "critical", label: `≤${thresholds.critical}% (Critical)`, color: "#FF4444" },
              { key: "high",     label: `≤${thresholds.high}% (High)`,         color: "#FF8C00" },
              { key: "medium",   label: `≤${thresholds.medium}% (Medium)`,     color: "#D9A84A" },
            ] as const).map(({ key, label, color }) => (
              <button
                key={key}
                onClick={() => setProgressFilter(key)}
                style={{
                  padding: "2px 8px", fontSize: 11, borderRadius: 3, cursor: "pointer",
                  border: `1px solid ${progressFilter === key ? color : "#30363d"}`,
                  background: progressFilter === key ? "#1a0e00" : "#0d1117",
                  color: progressFilter === key ? color : "#555",
                  fontWeight: progressFilter === key ? 700 : 400,
                }}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Threshold sliders panel ───────────────────────────────────────── */}
      {showThresholds && (
        <div style={{
          background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
          padding: "14px 16px", marginBottom: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <h4 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#e6edf3" }}>
              Enemy System Vulnerability Thresholds
            </h4>
            <span style={{ fontSize: 11, color: "#555" }}>
              Backend defaults: Critical≤{liveThresholds.critical}% · High≤{liveThresholds.high}% · Medium≤{liveThresholds.medium}%
            </span>
          </div>
          <p style={{ fontSize: 12, color: "#8b949e", margin: "0 0 14px" }}>
            Set the enemy control-progress cutoffs that define each vulnerability band.
            The progress bar colour in the table and the "Show" filter buttons update immediately.
            Absolute merit equivalents are shown below each slider for context (varies by state).
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0 32px" }}>
            <ThresholdSlider
              label="🔴 Critical — near collapse"
              color="#FF4444"
              value={thresholds.critical}
              onChange={v => setThresholds(t => ({ ...t, critical: v }))}
              max={thresholds.high - 1}
              defaultValue={liveThresholds.critical}
            />
            <ThresholdSlider
              label="🟠 High vulnerability"
              color="#FF8C00"
              value={thresholds.high}
              onChange={v => setThresholds(t => ({ ...t, high: v }))}
              min={thresholds.critical + 1}
              max={thresholds.medium - 1}
              defaultValue={liveThresholds.high}
            />
            <ThresholdSlider
              label="🟡 Medium vulnerability"
              color="#D9A84A"
              value={thresholds.medium}
              onChange={v => setThresholds(t => ({ ...t, medium: v }))}
              min={thresholds.high + 1}
              defaultValue={liveThresholds.medium}
            />
          </div>
          <p style={{ fontSize: 11, color: "#555", margin: "8px 0 0" }}>
            ℹ These are display-only overrides. To persist them to the database, update the
            <strong style={{ color: "#8b949e" }}> Target Analysis Weights</strong> section in
            the <strong style={{ color: "#8b949e" }}>Admin panel</strong> and re-run the analysis.
          </p>
        </div>
      )}

      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div style={{
        background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
        padding: "14px 16px", marginBottom: 14, display: "flex", flexDirection: "column", gap: 14,
      }}>
        {/* Attacker selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: "#8b949e", fontWeight: 600, minWidth: 80 }}>
            Your Power:
          </span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {allPowers.map(p => (
              <button
                key={p}
                onClick={() => {
                  setAttackerPower(p);
                  setTargetPowers(prev => prev.filter(t => t !== p));
                  setResults([]);
                }}
                style={{
                  padding: "3px 10px", fontSize: 12, borderRadius: 4, cursor: "pointer",
                  border: attackerPower === p ? "1px solid #58a6ff" : "1px solid #30363d",
                  background: attackerPower === p ? "#051d2c" : "#0d1117",
                  color: attackerPower === p ? "#58a6ff" : "#8b949e",
                  fontWeight: attackerPower === p ? 700 : 400,
                }}
              >
                {attackerPower === p ? "⚔ " : ""}{p}
              </button>
            ))}
          </div>
        </div>

        {/* Target selector */}
        <PowerMultiSelect
          label="Target Powers:"
          value={targetPowers}
          onChange={v => { setTargetPowers(v); setResults([]); }}
          allPowers={allPowers}
          exclude={attackerPower ? [attackerPower] : []}
        />

        {/* Run button */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={runAnalysis}
            disabled={!attackerPower || targetPowers.length === 0 || loading}
            style={{
              padding: "8px 24px", fontSize: 13, fontWeight: 700, borderRadius: 5,
              cursor: !attackerPower || targetPowers.length === 0 || loading ? "not-allowed" : "pointer",
              background: !attackerPower || targetPowers.length === 0 ? "#21262d" : "#D94A4A",
              color: !attackerPower || targetPowers.length === 0 ? "#555" : "#fff",
              border: "none",
            }}
          >
            {loading ? "Analysing…" : "⚔ Analyse Targets"}
          </button>
          {!attackerPower && <span style={{ fontSize: 12, color: "#8b949e" }}>Select your power first</span>}
          {attackerPower && targetPowers.length === 0 && <span style={{ fontSize: 12, color: "#8b949e" }}>Select at least one target power</span>}
          {results.length > 0 && !loading && (
            <span style={{ fontSize: 12, color: "#8b949e" }}>
              {sorted.length} / {results.length} target systems
              {primeCount > 0 && (
                <span style={{ marginLeft: 8, color: "#FF4444", fontWeight: 700 }}>
                  · {primeCount} PRIME
                </span>
              )}
              {contestedCount > 0 && (
                <span style={{ marginLeft: 8, color: "#FF8C00", fontWeight: 700 }}>
                  · {contestedCount} ⚔ CONTESTED
                </span>
              )}
            </span>
          )}
          {error && <span style={{ fontSize: 13, color: "#D94A4A" }}>{error}</span>}
        </div>
      </div>

      {/* ── Filter tabs by target power ───────────────────────────────────── */}
      {results.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
          <button
            onClick={() => setFilterPower("all")}
            style={{
              padding: "4px 12px", fontSize: 12, borderRadius: 4, cursor: "pointer",
              border: filterPower === "all" ? "1px solid #58a6ff" : "1px solid #30363d",
              background: filterPower === "all" ? "#051d2c" : "#161b22",
              color: filterPower === "all" ? "#58a6ff" : "#8b949e",
              fontWeight: filterPower === "all" ? 700 : 400,
            }}
          >
            All ({results.length})
          </button>
          {Object.entries(countsByPower).sort((a, b) => b[1] - a[1]).map(([p, n]) => (
            <button
              key={p}
              onClick={() => setFilterPower(p)}
              style={{
                padding: "4px 12px", fontSize: 12, borderRadius: 4, cursor: "pointer",
                border: filterPower === p ? "1px solid #D94A4A" : "1px solid #30363d",
                background: filterPower === p ? "#3d0000" : "#161b22",
                color: filterPower === p ? "#FF8C00" : "#8b949e",
                fontWeight: filterPower === p ? 700 : 400,
              }}
            >
              {p} ({n})
            </button>
          ))}
        </div>
      )}

      {/* ── Empty state ───────────────────────────────────────────────────── */}
      {!loading && results.length === 0 && !error && (
        <p style={{ color: "#8b949e", fontSize: 14, marginTop: 8 }}>
          {!attackerPower
            ? "Select your power and target powers above, then click Analyse Targets."
            : "Configure targets above and click Analyse Targets to see vulnerability scores."}
        </p>
      )}

      {/* ── Results table ─────────────────────────────────────────────────── */}
      {sorted.length > 0 && (
        <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid #30363d" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <Th col="score"                label="Score"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={90}
                    title="Vulnerability score — higher = better undermine target" />
                <Th col="system_name"          label="System"       sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th col="controlling_power"    label="Owner"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={160} />
                <Th col="power_state"          label="State"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={140} />
                <Th col="control_progress"     label="Progress"     sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={110}
                    title={`Enemy control progress. Red=CRITICAL (≤${thresholds.critical}%), Orange=HIGH (≤${thresholds.high}%), Yellow=MEDIUM (≤${thresholds.medium}%)`} />
                <Th col="days_to_downgrade"    label="Days"         sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={65}
                    title="Estimated days until state drops at current undermine rate." />
                <Th col="reinforcement"        label="Reinf."       sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={85} />
                <Th col="undermining"          label="Underm."      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={85} />
                <Th col="net"                  label="Net R–U"      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={85}
                    title="Positive = enemy is reinforcing. Negative = already losing ground." />
                <Th col="distance_from_attacker" label="Dist LY"   sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={75}
                    title="Distance from your nearest controlled system." />
                <Th col="trend"                label="Trend"        sortKey={sortKey} sortDir={sortDir} onSort={handleSort} width={55}
                    title="Change in enemy progress. ↘ = falling (good for you)" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((item, i) => {
                const r   = item.reinforcement ?? 0;
                const u   = item.undermining   ?? 0;
                const net = netValue(r, u, item.cp_decay);

                // Row tinting: contested = orange glow, highest threat = red glow
                const rowBg = item.contested    ? "#1a1000"
                            : item.score >= 1200 ? "#1a0000"
                            : item.score >= 900  ? "#150c00"
                            : i % 2 === 0 ? "#0d1117" : "#161b22";

                return (
                  <tr key={item.system_id64} style={{ background: rowBg }}>
                    {/* Score + threat band */}
                    <td style={{ padding: "8px 10px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <ThreatBand score={item.score} />
                        <span style={{ fontSize: 11, color: "#8b949e", paddingLeft: 1 }}>
                          {item.score.toFixed(0)}
                        </span>
                      </div>
                    </td>

                    {/* System name + reasons tooltip */}
                    <td style={{ padding: "8px 10px", whiteSpace: "nowrap" }}>
                      <div>
                        <a
href={`https://inara.cz/elite/starsystem/?search=${encodeURIComponent(item.system_name)}`}
                          target="_blank" rel="noreferrer"
                          style={{ color: "#58a6ff", textDecoration: "none", fontWeight: 500 }}
                        >
                          {item.system_name}
                        </a>
                      </div>
                      <div style={{ fontSize: 11, color: "#8b949e", marginTop: 2, lineHeight: 1.4 }}>
                        {item.reasons.map((r, idx) => <span key={idx}>{r}<br /></span>)}
                      </div>
                    </td>

                    {/* Controlling power */}
                    <td style={{ padding: "8px 10px", color: "#8b949e", fontSize: 12, whiteSpace: "nowrap" }}>
                      {item.controlling_power ?? "Unknown"}
                    </td>

                    {/* State badge + contested badge */}
                    <td style={{ padding: "8px 10px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <PPBadge state={item.power_state} />
                        {item.contested && <ContestedBadge />}
                      </div>
                    </td>

                    {/* Progress bar (threshold-aware) */}
                    <td style={{ padding: "8px 10px" }}>
                      <ProgressBar value={item.control_progress} thresholds={activeThr} />
                    </td>

                    {/* Days to downgrade */}
                    <td style={{ padding: "8px 10px", textAlign: "center" }}>
                      <DaysCell days={item.days_to_downgrade} />
                    </td>

                    {/* Reinforcement */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: "#4AD94A", fontVariantNumeric: "tabular-nums" }}>
                      {r > 0 ? r.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Undermining */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: u > r ? "#D94A4A" : u > 0 ? "#D9A84A" : "#555", fontVariantNumeric: "tabular-nums" }}>
                      {u > 0 ? u.toLocaleString() : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Net R–U — for enemy: negative = we are winning */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: net < 0 ? "#4AD94A" : net > 0 ? "#D94A4A" : "#8b949e", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                      {(r > 0 || u > 0)
                        ? <>{net >= 0 ? "+" : ""}{net.toLocaleString()}</>
                        : <span style={{ color: "#555" }}>—</span>}
                    </td>

                    {/* Distance */}
                    <td style={{ padding: "8px 10px", textAlign: "right", color: item.distance_from_attacker != null && item.distance_from_attacker <= 10 ? "#FF8C00" : "#8b949e" }}>
                      {item.distance_from_attacker != null
                        ? `${item.distance_from_attacker.toFixed(1)}`
                        : "—"}
                    </td>

                    {/* Trend */}
                    <td style={{ padding: "8px 10px", textAlign: "center" }}>
                      <TrendArrow trend={item.trend} />
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
