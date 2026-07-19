import { useState, useEffect, useCallback } from "react";
import {
  getAdminToken, setAdminToken, clearAdminToken, getAuthHeader, getAdminStatus,
  changePassword,
} from "../api/admin";

// ── Types ─────────────────────────────────────────────────────────────────────
interface IngestionRun {
  id: number;
  source: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  records_processed: number;
}

interface AdminStatus {
  recent_runs: IngestionRun[];
  spansh_next_run: string | null;
  edsm_next_run: string | null;
}

interface AdminSetting {
  key: string;
  value: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function apiPost(path: string) {
  const res = await fetch(path, { method: "POST", headers: { ...getAuthHeader() } });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { ...getAuthHeader() } });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function apiPatch(path: string, body: unknown) {
  const res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ── Default scoring weights (must match backend services/scoring.py DEFAULTS) ──
// Urgency scoring is automatic (progress/days-to-failure) — these weights tune bonuses
const DEFAULT_WEIGHTS: Record<string, number> = {
  // Fortify
  fortify_weight:          1,    // Global fortify score multiplier (1 = no change)
  fortify_near_center:    15,    // Bonus for systems near center (<15 LY)
  // Expand
  expand_unoccupied:      60,    // Base score for Unoccupied system
  expand_high_progress:   30,    // Bonus if PP activity > 50%
  expand_proximity:       25,    // Bonus for systems close to controlled space (<20 LY)
  expand_allegiance_match:15,    // Bonus if allegiance matches power
};

const WEIGHT_LABELS: Record<string, string> = {
  // Fortify
  fortify_weight:          "Fortify — Global urgency score multiplier",
  fortify_near_center:     "Fortify — Bonus: near center system (<15 LY)",
  // Expand
  expand_unoccupied:       "Expand — Base score for Unoccupied system",
  expand_high_progress:    "Expand — Bonus: high PP activity in system (>50%)",
  expand_proximity:        "Expand — Bonus: close to controlled system (<20 LY)",
  expand_allegiance_match: "Expand — Bonus: allegiance matches power",
};

// ── Target Analysis weights ───────────────────────────────────────────────────
// Keys must match backend services/scoring.py DEFAULTS exactly.
const DEFAULT_TARGET_WEIGHTS: Record<string, number> = {
  target_score_stronghold:   1000,
  target_score_fortified:     600,
  target_score_exploited:     200,
  target_score_contested:     800,
  target_progress_bonus_max:  300,
  target_prox_bonus_max:      150,
  target_dist_max_ly:          30,
  target_max_results:          50,
};

const TARGET_WEIGHT_LABELS: Record<string, string> = {
  target_score_stronghold:   "Target — Base score: Stronghold systems",
  target_score_fortified:    "Target — Base score: Fortified systems",
  target_score_exploited:    "Target — Base score: Exploited systems",
  target_score_contested:    "Target — Base score: Contested systems",
  target_progress_bonus_max: "Target — Max progress bonus (enemy at 0%)",
  target_prox_bonus_max:     "Target — Max proximity bonus (adjacent)",
  target_dist_max_ly:        "Target — Proximity falloff distance (LY)",
  target_max_results:        "Target — Max results returned per query",
};

// ── Target Analysis vulnerability thresholds (progress %) ───────────────────
const DEFAULT_TARGET_THRESHOLDS: Record<string, number> = {
  target_progress_critical: 10,   // ≤ this % → CRITICAL
  target_progress_high:     25,   // ≤ this % → HIGH
  target_progress_medium:   50,   // ≤ this % → MEDIUM
};

const TARGET_THRESHOLD_LABELS: Record<string, string> = {
  target_progress_critical: "🔴 Critical threshold — enemy nearly at collapse (%)",
  target_progress_high:     "🟠 High vulnerability threshold (%)",
  target_progress_medium:   "🟡 Medium vulnerability threshold (%)",
};

// ── Fortification alert thresholds (days-to-failure) ─────────────────────────
// Keys must match backend DEFAULTS exactly.  Values are in DAYS.
const DEFAULT_THRESHOLDS: Record<string, number> = {
  exploited_threshold_urgent:    7,
  exploited_threshold_warning:  21,
  fortified_threshold_urgent:    7,
  fortified_threshold_warning:  21,
  stronghold_threshold_urgent:   7,
  stronghold_threshold_warning: 21,
};

// Band widths used to compute absolute merit equivalents for display labels
const BAND_WIDTH: Record<string, number> = {
  exploited:  213_000,   // 333k − 120k
  fortified:  334_000,   // 667k − 333k
  stronghold: 334_000,   // open-ended proxy
};

interface ThresholdGroup {
  state: "exploited" | "fortified" | "stronghold";
  label: string;
  color: string;
}
const THRESHOLD_GROUPS: ThresholdGroup[] = [
  { state: "exploited",  label: "Exploited",  color: "#e67e22" },
  { state: "fortified",  label: "Fortified",  color: "#3b82d4" },
  { state: "stronghold", label: "Stronghold", color: "#9b59b6" },
];

// Helper: merit equivalent for a days threshold  (days × daily_net ≈ buffer at risk)
// We approximate using band_width as a "buffer proxy": pct_of_band = days / 7
// This is purely illustrative — actual value depends on live R/U rates.
// Instead, show the absolute merit band boundary and the days label directly.
function meritEquiv(state: ThresholdGroup["state"], days: number): string {
  const band = BAND_WIDTH[state];
  // If buffer = p × band, then at the threshold the buffer at risk ≈ (days/7) × band
  const equiv = Math.round((days / 7) * band);
  return equiv.toLocaleString();
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = { completed: "#4AD94A", failed: "#D94A4A", running: "#FF8C00" };
  return (
    <span style={{ background: colors[status] ?? "#999", color: "#fff", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
      {status}
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
interface Props { onClose: () => void }

export default function AdminPage({ onClose }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState(!!getAdminToken());

  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [settings,          setSettings]          = useState<Record<string, number>>({});
  const [thresholds,        setThresholds]        = useState<Record<string, number>>({ ...DEFAULT_THRESHOLDS });
  const [targetWeights,     setTargetWeights]     = useState<Record<string, number>>({ ...DEFAULT_TARGET_WEIGHTS });
  const [targetThresholds,  setTargetThresholds]  = useState<Record<string, number>>({ ...DEFAULT_TARGET_THRESHOLDS });
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ── Change-password form state ──────────────────────────────────────────────
  const [pwCurrent,  setPwCurrent]  = useState("");
  const [pwNew,      setPwNew]      = useState("");
  const [pwConfirm,  setPwConfirm]  = useState("");
  const [pwSaving,   setPwSaving]   = useState(false);
  const [pwError,    setPwError]    = useState<string | null>(null);
  const [pwSuccess,  setPwSuccess]  = useState(false);

  const loadData = useCallback(() => {
    if (!getAdminToken()) return;
    setLoading(true);
    Promise.all([
      getAdminStatus(),
      apiGet<AdminSetting[]>("/api/admin/settings"),
    ])
      .then(([st, sets]) => {
        setStatus(st);
        const w:  Record<string, number> = { ...DEFAULT_WEIGHTS };
        const t:  Record<string, number> = { ...DEFAULT_THRESHOLDS };
        const tw: Record<string, number> = { ...DEFAULT_TARGET_WEIGHTS };
        const tt: Record<string, number> = { ...DEFAULT_TARGET_THRESHOLDS };
        sets.forEach((s) => {
          if (s.key in w)  w[s.key]  = parseFloat(s.value);
          if (s.key in t)  t[s.key]  = parseFloat(s.value);
          if (s.key in tw) tw[s.key] = parseFloat(s.value);
          if (s.key in tt) tt[s.key] = parseFloat(s.value);
        });
        setSettings(w);
        setThresholds(t);
        setTargetWeights(tw);
        setTargetThresholds(tt);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (isLoggedIn) loadData(); }, [isLoggedIn]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoginError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
      });
      if (!res.ok) throw new Error("Invalid credentials");
      const data = await res.json();
      setAdminToken(data.access_token);
      setIsLoggedIn(true);
    } catch (err: unknown) {
      setLoginError(err instanceof Error ? err.message : "Login failed");
    }
  }

  function handleLogout() {
    clearAdminToken();
    setIsLoggedIn(false);
    setStatus(null);
  }

  async function triggerIngest(source: "spansh" | "edsm") {
    setActionMsg(null);
    try {
      const path = source === "spansh" ? "/api/admin/ingest/spansh" : "/api/admin/ingest/edsm";
      await apiPost(path);
      setActionMsg(`${source === "spansh" ? "Spansh" : "EDSM"} ingest started in background.`);
      setTimeout(loadData, 3000);
    } catch (err: unknown) {
      setActionMsg(`Error: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function saveSettings() {
    setSettingsSaved(false);
    try {
      const payload = [
        ...Object.entries(settings),
        ...Object.entries(thresholds),
        ...Object.entries(targetWeights),
        ...Object.entries(targetThresholds),
      ].map(([key, value]) => ({ key, value: String(value) }));
      await apiPatch("/api/admin/settings", payload);
      setSettingsSaved(true);
      setTimeout(() => setSettingsSaved(false), 3000);
    } catch (err: unknown) {
      setActionMsg(`Save error: ${err instanceof Error ? err.message : err}`);
    }
  }

  const cardStyle: React.CSSProperties = {
    background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, padding: 20, marginBottom: 16,
  };

  // ── Login screen ────────────────────────────────────────────────────────────
  if (!isLoggedIn) {
    return (
      <div style={{ padding: 32, fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: "#1f2328", maxWidth: 400 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Admin Login</h2>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 20, color: "#57606a" }}>×</button>
        </div>
        <form onSubmit={handleLogin}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 13, marginBottom: 4, color: "#57606a" }}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #e5e7eb", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 13, marginBottom: 4, color: "#57606a" }}>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #e5e7eb", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }} />
          </div>
          {loginError && <p style={{ color: "#D94A4A", fontSize: 13, margin: "0 0 12px" }}>{loginError}</p>}
          <button type="submit" style={{ width: "100%", padding: "10px 0", background: "#3b82d4", color: "#fff", border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
            Sign In
          </button>
        </form>
      </div>
    );
  }

  // ── Admin panel ─────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: "20px 24px", fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: "#1f2328", maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Admin Panel</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={loadData} style={{ padding: "6px 14px", fontSize: 13, border: "1px solid #e5e7eb", borderRadius: 6, cursor: "pointer", background: "#f7f8fa" }}>
            Refresh
          </button>
          <button onClick={handleLogout} style={{ padding: "6px 14px", fontSize: 13, border: "1px solid #e5e7eb", borderRadius: 6, cursor: "pointer", background: "#f7f8fa", color: "#57606a" }}>
            Sign Out
          </button>
          <button onClick={onClose} style={{ padding: "6px 14px", fontSize: 13, border: "none", borderRadius: 6, cursor: "pointer", background: "none", lineHeight: 1 }}>×</button>
        </div>
      </div>

      {actionMsg && (
        <div style={{ padding: "10px 14px", background: "#f0f9ff", border: "1px solid #3b82d4", borderRadius: 6, fontSize: 13, marginBottom: 16 }}>
          {actionMsg}
        </div>
      )}

      {/* Data Ingestion */}
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700 }}>Data Ingestion</h3>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <div style={{ flex: 1, minWidth: 200, background: "#f7f8fa", borderRadius: 6, padding: 14, border: "1px solid #e5e7eb" }}>
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 14 }}>Spansh PP Ingest</div>
            <div style={{ fontSize: 12, color: "#57606a", marginBottom: 8 }}>
              Streams <code style={{ fontSize: 11 }}>systems_populated.json.gz</code> from Spansh, populates PP system snapshots. First run may take several minutes.
            </div>
            {status?.spansh_next_run && <div style={{ fontSize: 11, color: "#57606a", marginBottom: 8 }}>Next scheduled: {new Date(status.spansh_next_run).toLocaleString()}</div>}
            <button onClick={() => triggerIngest("spansh")} style={{ padding: "6px 14px", fontSize: 13, background: "#3b82d4", color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontWeight: 600 }}>
              Run Now
            </button>
          </div>
          <div style={{ flex: 1, minWidth: 200, background: "#f7f8fa", borderRadius: 6, padding: 14, border: "1px solid #e5e7eb", opacity: 0.55 }}>
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 14 }}>EDSM Sync <span style={{ fontSize: 11, fontWeight: 400, color: "#999" }}>(reserved)</span></div>
            <div style={{ fontSize: 12, color: "#57606a", marginBottom: 8 }}>Additional data enrichment from EDSM. Not yet active.</div>
            {status?.edsm_next_run && <div style={{ fontSize: 11, color: "#57606a", marginBottom: 8 }}>Next scheduled: {new Date(status.edsm_next_run).toLocaleString()}</div>}
            <button disabled style={{ padding: "6px 14px", fontSize: 13, background: "#ccc", color: "#fff", border: "none", borderRadius: 5, cursor: "not-allowed", fontWeight: 600 }}>
              Run Now
            </button>
          </div>
        </div>

        {/* Ingestion history */}
        <h4 style={{ margin: "12px 0 8px", fontSize: 13, fontWeight: 700, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.04em" }}>Recent Runs</h4>
        {loading && <p style={{ fontSize: 13, color: "#57606a" }}>Loading…</p>}
        {status?.recent_runs && status.recent_runs.length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f7f8fa" }}>
                  {["Source", "Started", "Completed", "Status", "Records"].map((h) => (
                    <th key={h} style={{ padding: "8px 10px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#57606a", textTransform: "uppercase", borderBottom: "2px solid #e5e7eb" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.recent_runs.map((run, i) => (
                  <tr key={run.id} style={{ background: i % 2 === 0 ? "#fff" : "#f7f8fa" }}>
                    <td style={{ padding: "7px 10px", fontWeight: 600, textTransform: "capitalize" }}>{run.source}</td>
                    <td style={{ padding: "7px 10px", color: "#57606a" }}>{new Date(run.started_at).toLocaleString()}</td>
                    <td style={{ padding: "7px 10px", color: "#57606a" }}>{run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}</td>
                    <td style={{ padding: "7px 10px" }}><StatusBadge status={run.status} /></td>
                    <td style={{ padding: "7px 10px", textAlign: "right" }}>{run.records_processed.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !loading && <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>No ingestion runs yet.</p>
        )}
      </div>

      {/* Scoring Weights */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Scoring Weights</h3>
          <button onClick={saveSettings} style={{ padding: "6px 16px", fontSize: 13, background: "#4AD94A", color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontWeight: 600 }}>
            {settingsSaved ? "✓ Saved!" : "Save All Settings"}
          </button>
        </div>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 16px" }}>
          Adjust point values for each scoring rule. Use the slider for quick adjustments or type a value directly.
          Higher values make that condition more influential in recommendation ranking.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 40px" }}>
          {Object.keys(DEFAULT_WEIGHTS).map((key) => {
            const val = settings[key] ?? DEFAULT_WEIGHTS[key];
            const def = DEFAULT_WEIGHTS[key];
            const changed = val !== def;
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <label style={{ fontSize: 12, color: changed ? "#1f2328" : "#57606a", fontWeight: changed ? 600 : 400 }}>
                    {WEIGHT_LABELS[key] ?? key}
                  </label>
                  {changed && (
                    <button
                      onClick={() => setSettings((prev) => ({ ...prev, [key]: def }))}
                      title={`Reset to default (${def})`}
                      style={{ fontSize: 10, color: "#57606a", background: "none", border: "1px solid #e5e7eb", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}
                    >
                      reset
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="range" min={0} max={200} step={1}
                    value={val}
                    onChange={(e) => setSettings((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                    style={{ flex: 1, accentColor: changed ? "#3b82d4" : "#ccc" }}
                  />
                  <input
                    type="number" min={0} max={9999} step={1}
                    value={val}
                    onChange={(e) => {
                      const n = parseFloat(e.target.value);
                      if (!isNaN(n) && n >= 0) setSettings((prev) => ({ ...prev, [key]: n }));
                    }}
                    style={{
                      width: 62, padding: "4px 6px", fontSize: 13, fontWeight: 600,
                      border: `1px solid ${changed ? "#3b82d4" : "#e5e7eb"}`,
                      borderRadius: 5, textAlign: "right",
                      color: changed ? "#3b82d4" : "#57606a",
                      outline: "none",
                    }}
                  />
                </div>
                <div style={{ fontSize: 10, color: "#bbb", marginTop: 1 }}>default: {def}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Fortification Alert Thresholds */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Fortification Alert Thresholds</h3>
          <span style={{ fontSize: 11, color: "#57606a" }}>Saved with "Save All Settings" above</span>
        </div>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 18px" }}>
          Set the <strong>days-to-failure</strong> cutoffs that trigger each alert band, independently per power state.
          A system whose buffer will be exhausted within the <em>Urgent</em> threshold fires a 🔴 URGENT alert;
          within <em>Warning</em> fires a 🟡 WARNING alert; beyond Warning is 🔵 MONITOR only.
          The merit equivalent shown is illustrative (assumes 1/7 of band used per day at average rate).
        </p>

        {THRESHOLD_GROUPS.map(({ state, label, color }) => {
          const urgentKey  = `${state}_threshold_urgent`;
          const warningKey = `${state}_threshold_warning`;
          const urgentVal  = thresholds[urgentKey]  ?? DEFAULT_THRESHOLDS[urgentKey];
          const warningVal = thresholds[warningKey] ?? DEFAULT_THRESHOLDS[warningKey];
          const urgentDef  = DEFAULT_THRESHOLDS[urgentKey];
          const warningDef = DEFAULT_THRESHOLDS[warningKey];
          const urgentChanged  = urgentVal  !== urgentDef;
          const warningChanged = warningVal !== warningDef;

          return (
            <div key={state} style={{ marginBottom: 20 }}>
              {/* State header */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <div style={{ width: 10, height: 10, borderRadius: "50%", background: color }} />
                <span style={{ fontSize: 13, fontWeight: 700, color }}>{label}</span>
                <span style={{ fontSize: 11, color: "#57606a" }}>band width: {BAND_WIDTH[state].toLocaleString()} merits</span>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 40px" }}>
                {/* Urgent threshold */}
                {[
                  { key: urgentKey,  val: urgentVal,  def: urgentDef,  changed: urgentChanged,  band: "🔴 Urgent",  setter: (v: number) => setThresholds((p) => ({ ...p, [urgentKey]: v })),  accent: "#D94A4A" },
                  { key: warningKey, val: warningVal, def: warningDef, changed: warningChanged, band: "🟡 Warning", setter: (v: number) => setThresholds((p) => ({ ...p, [warningKey]: v })), accent: "#FF8C00" },
                ].map(({ key, val, def, changed, band, setter, accent }) => (
                  <div key={key}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <label style={{ fontSize: 12, color: changed ? "#1f2328" : "#57606a", fontWeight: changed ? 600 : 400 }}>
                        {band} — fire when days to failure &lt; threshold
                      </label>
                      {changed && (
                        <button
                          onClick={() => setter(def)}
                          title={`Reset to default (${def}d)`}
                          style={{ fontSize: 10, color: "#57606a", background: "none", border: "1px solid #e5e7eb", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}
                        >
                          reset
                        </button>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="range" min={1} max={90} step={1}
                        value={val}
                        onChange={(e) => setter(Number(e.target.value))}
                        style={{ flex: 1, accentColor: changed ? accent : "#ccc" }}
                      />
                      <input
                        type="number" min={1} max={999} step={1}
                        value={val}
                        onChange={(e) => {
                          const n = parseInt(e.target.value, 10);
                          if (!isNaN(n) && n >= 1) setter(n);
                        }}
                        style={{
                          width: 56, padding: "4px 6px", fontSize: 13, fontWeight: 600,
                          border: `1px solid ${changed ? accent : "#e5e7eb"}`,
                          borderRadius: 5, textAlign: "right",
                          color: changed ? accent : "#57606a",
                          outline: "none",
                        }}
                      />
                      <span style={{ fontSize: 11, color: "#57606a", whiteSpace: "nowrap" }}>days</span>
                    </div>
                    <div style={{ fontSize: 10, color: "#bbb", marginTop: 1 }}>
                      default: {def}d · ≈ {meritEquiv(state, val)} merits at risk
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Target Analysis Weights */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Target Analysis Weights</h3>
          <span style={{ fontSize: 11, color: "#57606a" }}>Saved with "Save All Settings" above</span>
        </div>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 14px" }}>
          Base scores for each enemy state tier, progress bonus, proximity bonus, and max results per query.
          Higher base scores push that tier higher in the ranking. Changes take effect on the next analysis run.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 40px", marginBottom: 20 }}>
          {Object.keys(DEFAULT_TARGET_WEIGHTS).map((key) => {
            const val = targetWeights[key] ?? DEFAULT_TARGET_WEIGHTS[key];
            const def = DEFAULT_TARGET_WEIGHTS[key];
            const changed = val !== def;
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <label style={{ fontSize: 12, color: changed ? "#1f2328" : "#57606a", fontWeight: changed ? 600 : 400 }}>
                    {TARGET_WEIGHT_LABELS[key] ?? key}
                  </label>
                  {changed && (
                    <button
                      onClick={() => setTargetWeights((prev) => ({ ...prev, [key]: def }))}
                      title={`Reset to default (${def})`}
                      style={{ fontSize: 10, color: "#57606a", background: "none", border: "1px solid #e5e7eb", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}
                    >
                      reset
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="range" min={0} max={2000} step={10}
                    value={val}
                    onChange={(e) => setTargetWeights((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                    style={{ flex: 1, accentColor: changed ? "#D94A4A" : "#ccc" }}
                  />
                  <input
                    type="number" min={0} max={9999} step={1}
                    value={val}
                    onChange={(e) => {
                      const n = parseFloat(e.target.value);
                      if (!isNaN(n) && n >= 0) setTargetWeights((prev) => ({ ...prev, [key]: n }));
                    }}
                    style={{
                      width: 70, padding: "4px 6px", fontSize: 13, fontWeight: 600,
                      border: `1px solid ${changed ? "#D94A4A" : "#e5e7eb"}`,
                      borderRadius: 5, textAlign: "right",
                      color: changed ? "#D94A4A" : "#57606a",
                      outline: "none",
                    }}
                  />
                </div>
                <div style={{ fontSize: 10, color: "#bbb", marginTop: 1 }}>default: {def}</div>
              </div>
            );
          })}
        </div>

        {/* Vulnerability progress thresholds */}
        <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: "#57606a", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Vulnerability Progress Thresholds
        </h4>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 12px" }}>
          Enemy control-progress % cutoffs for vulnerability bands (Critical / High / Medium).
          These gate the progress bar colours and reason-text in the Target Analysis view.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "14px 30px" }}>
          {Object.keys(DEFAULT_TARGET_THRESHOLDS).map((key) => {
            const val = targetThresholds[key] ?? DEFAULT_TARGET_THRESHOLDS[key];
            const def = DEFAULT_TARGET_THRESHOLDS[key];
            const changed = val !== def;
            const accent = key.includes("critical") ? "#D94A4A" : key.includes("high") ? "#FF8C00" : "#D9A84A";
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <label style={{ fontSize: 12, color: changed ? "#1f2328" : "#57606a", fontWeight: changed ? 600 : 400 }}>
                    {TARGET_THRESHOLD_LABELS[key] ?? key}
                  </label>
                  {changed && (
                    <button
                      onClick={() => setTargetThresholds((prev) => ({ ...prev, [key]: def }))}
                      title={`Reset to default (${def}%)`}
                      style={{ fontSize: 10, color: "#57606a", background: "none", border: "1px solid #e5e7eb", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}
                    >
                      reset
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="range" min={1} max={99} step={1}
                    value={val}
                    onChange={(e) => setTargetThresholds((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                    style={{ flex: 1, accentColor: changed ? accent : "#ccc" }}
                  />
                  <input
                    type="number" min={1} max={99} step={1}
                    value={val}
                    onChange={(e) => {
                      const n = parseInt(e.target.value, 10);
                      if (!isNaN(n) && n >= 1 && n <= 99) setTargetThresholds((prev) => ({ ...prev, [key]: n }));
                    }}
                    style={{
                      width: 56, padding: "4px 6px", fontSize: 13, fontWeight: 600,
                      border: `1px solid ${changed ? accent : "#e5e7eb"}`,
                      borderRadius: 5, textAlign: "right",
                      color: changed ? accent : "#57606a",
                      outline: "none",
                    }}
                  />
                  <span style={{ fontSize: 11, color: "#bbb" }}>%</span>
                </div>
                <div style={{ fontSize: 10, color: "#bbb", marginTop: 1 }}>default: {def}%</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Change Password ─────────────────────────────────────────────────── */}
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700 }}>Change Password</h3>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 16px" }}>
          Enter your current password to verify your identity, then set a new one.
          Minimum 8 characters.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 380 }}>
          {/* Current password */}
          <div>
            <label style={{ display: "block", fontSize: 12, color: "#57606a", marginBottom: 4 }}>
              Current password
            </label>
            <input
              type="password"
              value={pwCurrent}
              onChange={e => { setPwCurrent(e.target.value); setPwError(null); setPwSuccess(false); }}
              autoComplete="current-password"
              style={pwInputStyle}
            />
          </div>

          {/* New password */}
          <div>
            <label style={{ display: "block", fontSize: 12, color: "#57606a", marginBottom: 4 }}>
              New password
              <span style={{ marginLeft: 6, fontSize: 11, color: "#bbb" }}>(min 8 characters)</span>
            </label>
            <input
              type="password"
              value={pwNew}
              onChange={e => { setPwNew(e.target.value); setPwError(null); setPwSuccess(false); }}
              autoComplete="new-password"
              style={{
                ...pwInputStyle,
                borderColor: pwNew.length > 0 && pwNew.length < 8 ? "#D94A4A" : "#e5e7eb",
              }}
            />
            {/* Strength indicator */}
            {pwNew.length > 0 && (
              <div style={{ marginTop: 4, display: "flex", gap: 3 }}>
                {[8, 12, 16, 20].map(threshold => (
                  <div
                    key={threshold}
                    style={{
                      flex: 1, height: 3, borderRadius: 2,
                      background: pwNew.length >= threshold ? (
                        threshold <= 8  ? "#D94A4A" :
                        threshold <= 12 ? "#FF8C00" :
                        threshold <= 16 ? "#D9A84A" : "#4AD94A"
                      ) : "#e5e7eb",
                    }}
                  />
                ))}
                <span style={{ fontSize: 10, color: "#bbb", marginLeft: 4, whiteSpace: "nowrap" }}>
                  {pwNew.length < 8  ? "too short" :
                   pwNew.length < 12 ? "weak" :
                   pwNew.length < 16 ? "fair" :
                   pwNew.length < 20 ? "good" : "strong"}
                </span>
              </div>
            )}
          </div>

          {/* Confirm new password */}
          <div>
            <label style={{ display: "block", fontSize: 12, color: "#57606a", marginBottom: 4 }}>
              Confirm new password
            </label>
            <input
              type="password"
              value={pwConfirm}
              onChange={e => { setPwConfirm(e.target.value); setPwError(null); setPwSuccess(false); }}
              autoComplete="new-password"
              style={{
                ...pwInputStyle,
                borderColor: pwConfirm.length > 0 && pwConfirm !== pwNew ? "#D94A4A" : "#e5e7eb",
              }}
            />
            {pwConfirm.length > 0 && pwConfirm !== pwNew && (
              <p style={{ fontSize: 11, color: "#D94A4A", margin: "3px 0 0" }}>
                Passwords do not match
              </p>
            )}
          </div>

          {/* Error / success feedback */}
          {pwError && (
            <p style={{ fontSize: 13, color: "#D94A4A", margin: 0, padding: "8px 10px", background: "#fff0f0", border: "1px solid #f5c0c0", borderRadius: 5 }}>
              {pwError}
            </p>
          )}
          {pwSuccess && (
            <p style={{ fontSize: 13, color: "#1a7a2a", margin: 0, padding: "8px 10px", background: "#f0fff4", border: "1px solid #b2dfbd", borderRadius: 5 }}>
              ✓ Password changed successfully.
            </p>
          )}

          {/* Submit */}
          <button
            disabled={
              pwSaving ||
              !pwCurrent ||
              pwNew.length < 8 ||
              pwNew !== pwConfirm
            }
            onClick={async () => {
              setPwSaving(true);
              setPwError(null);
              setPwSuccess(false);
              try {
                await changePassword(pwCurrent, pwNew, pwConfirm);
                setPwSuccess(true);
                setPwCurrent("");
                setPwNew("");
                setPwConfirm("");
              } catch (err: unknown) {
                setPwError(err instanceof Error ? err.message : "Change failed");
              } finally {
                setPwSaving(false);
              }
            }}
            style={{
              padding: "9px 20px", fontSize: 13, fontWeight: 700,
              background: pwSaving || !pwCurrent || pwNew.length < 8 || pwNew !== pwConfirm
                ? "#ccc" : "#3b82d4",
              color: "#fff", border: "none", borderRadius: 6,
              cursor: pwSaving || !pwCurrent || pwNew.length < 8 || pwNew !== pwConfirm
                ? "not-allowed" : "pointer",
              alignSelf: "flex-start",
            }}
          >
            {pwSaving ? "Saving…" : "Change Password"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Shared input style for password fields ─────────────────────────────────────
const pwInputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px",
  border: "1px solid #e5e7eb", borderRadius: 6,
  fontSize: 14, boxSizing: "border-box", outline: "none",
};
