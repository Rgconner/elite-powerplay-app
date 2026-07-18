import React, { useState, useEffect, useCallback } from "react";
import {
  getAdminToken, setAdminToken, clearAdminToken, getAuthHeader, getAdminStatus,
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

// ── Default scoring weights ───────────────────────────────────────────────────
const DEFAULT_WEIGHTS: Record<string, number> = {
  fortify_undermined: 50,
  fortify_turmoil: 40,
  fortify_low_influence: 20,
  fortify_trend_down: 15,
  fortify_not_controlling: 25,
  fortify_near_center: 10,
  expand_uncontrolled: 40,
  expand_proximity: 20,
  expand_pp_state: 30,
  expand_allegiance_gap: 10,
  expand_low_competition: 15,
};

const WEIGHT_LABELS: Record<string, string> = {
  fortify_undermined: "Fortify — Undermined state",
  fortify_turmoil: "Fortify — Turmoil state",
  fortify_low_influence: "Fortify — Low influence (<40%)",
  fortify_trend_down: "Fortify — Declining influence",
  fortify_not_controlling: "Fortify — Not controlling system",
  fortify_near_center: "Fortify — Near center system (<15 LY)",
  expand_uncontrolled: "Expand — No controlling faction",
  expand_proximity: "Expand — Close to controlled system (<20 LY)",
  expand_pp_state: "Expand — Expansion / InPrepareRadius state",
  expand_allegiance_gap: "Expand — No same-allegiance competitor",
  expand_low_competition: "Expand — Low faction count (<3)",
};

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
  const [settings, setSettings] = useState<Record<string, number>>({});
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadData = useCallback(() => {
    if (!getAdminToken()) return;
    setLoading(true);
    Promise.all([
      getAdminStatus(),
      apiGet<AdminSetting[]>("/api/admin/settings"),
    ])
      .then(([st, sets]) => {
        setStatus(st);
        const w: Record<string, number> = { ...DEFAULT_WEIGHTS };
        sets.forEach((s) => { if (s.key in w) w[s.key] = parseFloat(s.value); });
        setSettings(w);
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
      const payload = Object.entries(settings).map(([key, value]) => ({ key, value: String(value) }));
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
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 14 }}>Spansh Factions</div>
            <div style={{ fontSize: 12, color: "#57606a", marginBottom: 8 }}>Downloads factions.json.gz, populates faction/system/presence tables.</div>
            {status?.spansh_next_run && <div style={{ fontSize: 11, color: "#57606a", marginBottom: 8 }}>Next run: {new Date(status.spansh_next_run).toLocaleString()}</div>}
            <button onClick={() => triggerIngest("spansh")} style={{ padding: "6px 14px", fontSize: 13, background: "#3b82d4", color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontWeight: 600 }}>
              Run Now
            </button>
          </div>
          <div style={{ flex: 1, minWidth: 200, background: "#f7f8fa", borderRadius: 6, padding: 14, border: "1px solid #e5e7eb" }}>
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 14 }}>EDSM Power Play Sync</div>
            <div style={{ fontSize: 12, color: "#57606a", marginBottom: 8 }}>Fetches PP state + influence for each known system from EDSM API.</div>
            {status?.edsm_next_run && <div style={{ fontSize: 11, color: "#57606a", marginBottom: 8 }}>Next run: {new Date(status.edsm_next_run).toLocaleString()}</div>}
            <button onClick={() => triggerIngest("edsm")} style={{ padding: "6px 14px", fontSize: 13, background: "#7c5cd8", color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontWeight: 600 }}>
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Scoring Weights</h3>
          <button onClick={saveSettings} style={{ padding: "6px 16px", fontSize: 13, background: "#4AD94A", color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontWeight: 600 }}>
            {settingsSaved ? "Saved!" : "Save Weights"}
          </button>
        </div>
        <p style={{ fontSize: 12, color: "#57606a", margin: "0 0 16px" }}>Adjust the point values for each scoring rule. Higher values make that condition more influential in the recommendation ranking.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 32px" }}>
          {Object.keys(DEFAULT_WEIGHTS).map((key) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <label style={{ fontSize: 13, flex: 1, color: "#1f2328" }}>{WEIGHT_LABELS[key] ?? key}</label>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="range" min={0} max={100} step={5}
                  value={settings[key] ?? DEFAULT_WEIGHTS[key]}
                  onChange={(e) => setSettings((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                  style={{ width: 100 }}
                />
                <span style={{ fontSize: 13, fontWeight: 600, width: 28, textAlign: "right", color: "#3b82d4" }}>
                  {settings[key] ?? DEFAULT_WEIGHTS[key]}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
