/**
 * TelemetryPage — operational feed health dashboard.
 *
 * Requires admin authentication (same JWT as Admin page).
 * Shows a 2×2 grid of feed panels plus recent ingestion history.
 * Auto-refreshes every 60 seconds.
 */

import { useState, useEffect, useCallback } from "react";
import {
  getAdminToken, setAdminToken, clearAdminToken,
  getTelemetry,
  type TelemetryStatus, type TelemetryFeedIngest, type TelemetryFeedEddn,
  type TelemetryFeedEnrichment, type TelemetryRunSummary,
} from "../api/admin";

// ── Styling constants (dark theme matching the rest of the app) ───────────────

const BG   = "#0d1117";
const CARD = "#161b22";
const BORDER = "#30363d";
const TEXT  = "#e6edf3";
const MUTED = "#8b949e";

const STATUS_COLOR: Record<string, string> = {
  green:  "#22c55e",
  yellow: "#f59e0b",
  red:    "#ef4444",
};
const STATUS_LABEL: Record<string, string> = {
  green: "OK", yellow: "Stale", red: "Failed",
};

function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60)     return `${secs}s ago`;
  if (secs < 3600)   return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86_400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86_400)}d ago`;
}

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60)  return `${s.toFixed(0)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtBytes(n: number | null | undefined): string {
  if (n == null || n === 0) return "—";
  if (n < 1_024)       return `${n} B`;
  if (n < 1_048_576)   return `${(n / 1_024).toFixed(1)} KB`;
  if (n < 1_073_741_824) return `${(n / 1_048_576).toFixed(1)} MB`;
  return `${(n / 1_073_741_824).toFixed(2)} GB`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: "green" | "yellow" | "red" }) {
  return (
    <span style={{
      display: "inline-block", width: 10, height: 10, borderRadius: "50%",
      background: STATUS_COLOR[status], flexShrink: 0,
    }} />
  );
}

function CardHeader({ label, status }: { label: string; status: "green" | "yellow" | "red" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      <StatusDot status={status} />
      <span style={{ fontSize: 14, fontWeight: 700, color: TEXT }}>{label}</span>
      <span style={{
        marginLeft: "auto", fontSize: 11, fontWeight: 600,
        color: STATUS_COLOR[status],
        background: `${STATUS_COLOR[status]}22`,
        border: `1px solid ${STATUS_COLOR[status]}44`,
        borderRadius: 10, padding: "1px 8px",
      }}>
        {STATUS_LABEL[status]}
      </span>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 5 }}>
      <span style={{ color: MUTED }}>{label}</span>
      <span style={{ color: TEXT, fontVariantNumeric: "tabular-nums" }}>{value ?? "—"}</span>
    </div>
  );
}

function Divider() {
  return <div style={{ borderTop: `1px solid ${BORDER}`, margin: "10px 0" }} />;
}

function RunRow({ run }: { run: TelemetryRunSummary }) {
  const statusColor: Record<string, string> = {
    completed: "#22c55e", failed: "#ef4444", running: "#f59e0b",
  };
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "70px 1fr 55px 55px 52px 52px",
      gap: 5, fontSize: 11, padding: "4px 0", borderBottom: `1px solid ${BORDER}`,
      alignItems: "center",
    }}>
      <span style={{ color: statusColor[run.status] ?? MUTED, fontWeight: 600 }}>
        {run.status}
      </span>
      <span style={{ color: MUTED }}>{fmtAgo(run.completed_at ?? run.started_at)}</span>
      <span style={{ color: TEXT, textAlign: "right" }}>{fmtNum(run.records_processed)}</span>
      <span style={{ color: TEXT, textAlign: "right" }}>{fmtDuration(run.duration_seconds)}</span>
      <span style={{ color: TEXT, textAlign: "right" }}>{fmtBytes(run.bytes_downloaded)}</span>
      <span style={{ color: run.api_errors > 0 ? STATUS_COLOR.yellow : MUTED, textAlign: "right" }}>
        {run.api_errors > 0 ? `⚠ ${run.api_errors}` : "—"}
      </span>
    </div>
  );
}

function IngestPanel({ title, feed }: { title: string; feed: TelemetryFeedIngest }) {
  const lr = feed.last_run;
  return (
    <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16 }}>
      <CardHeader label={title} status={feed.status} />
      <KV label="Last completed"  value={fmtAgo(lr?.completed_at ?? lr?.started_at)} />
      <KV label="Records"         value={fmtNum(lr?.records_processed)} />
      <KV label="Duration"        value={fmtDuration(lr?.duration_seconds)} />
      <KV label="Pages fetched"   value={fmtNum(lr?.pages_fetched)} />
      <KV label="Downloaded"      value={fmtBytes(lr?.bytes_downloaded)} />
      <KV label="API calls"       value={fmtNum(lr?.api_calls_made)} />
      <KV label="API errors"      value={lr?.api_errors != null && lr.api_errors > 0 ? `⚠ ${lr.api_errors}` : "0"} />
      <KV label="Next run"        value={feed.next_run_at ? fmtAgo(feed.next_run_at) + " (scheduled)" : "—"} />
      {lr?.error_detail && (
        <div style={{
          marginTop: 8, padding: "6px 8px", background: "#2d1a1a", borderRadius: 4,
          fontSize: 11, color: "#f87171", fontFamily: "monospace", wordBreak: "break-word",
        }}>
          {lr.error_detail}
        </div>
      )}
      {feed.history.length > 0 && (
        <>
          <Divider />
          <div style={{ fontSize: 11, color: MUTED, fontWeight: 600, marginBottom: 6 }}>
            Recent runs — Status / Age / Records / Duration / Downloaded / Errors
          </div>
          {feed.history.map((r) => <RunRow key={r.id} run={r} />)}
        </>
      )}
    </div>
  );
}

function EddnPanel({ feed }: { feed: TelemetryFeedEddn }) {
  // Prefer the instrumented msgs/min; fall back to events_last_5min/5
  const msgsPerMin = feed.messages_per_min != null
    ? feed.messages_per_min.toFixed(1)
    : feed.events_last_5min != null
      ? (feed.events_last_5min / 5).toFixed(1)
      : null;

  // Schema breakdown — top 5 by count
  const topSchemas = Object.entries(feed.top_schemas ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  // Abbreviate the schema URL to just the last path segment for display
  const schemaLabel = (s: string) => s.split("/").filter(Boolean).pop() ?? s;

  return (
    <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16 }}>
      <CardHeader label="EDDN Real-Time Stream" status={feed.status} />
      <KV label="Last event"        value={fmtAgo(feed.last_event_ts)} />
      <KV label="Stats recorded"    value={fmtAgo(feed.recorded_at)} />
      <KV label="Msgs/min (live)"   value={msgsPerMin ?? "—"} />
      <KV label="Events last 5min"  value={fmtNum(feed.events_last_5min)} />
      <KV label="Total events"      value={fmtNum(feed.events_total)} />
      <KV label="Total messages"    value={fmtNum(feed.messages_received_total)} />
      <KV label="Data received"     value={fmtBytes(feed.bytes_received_total)} />
      <Divider />
      <KV label="Non-journal msgs"  value={fmtNum(feed.skipped_schema_total)} />
      <KV label="Non-PP journal"    value={fmtNum(feed.skipped_event_total)} />
      <KV label="Dedup rejected"    value={fmtNum(feed.dedup_rejected)} />
      <KV label="Decode errors"     value={feed.decode_errors > 0 ? `⚠ ${feed.decode_errors}` : "0"} />
      <KV label="Listener up since" value={fmtAgo(feed.listener_started_at)} />
      {topSchemas.length > 0 && (
        <>
          <Divider />
          <div style={{ fontSize: 11, color: MUTED, fontWeight: 600, marginBottom: 6 }}>
            Top schemas seen (all time)
          </div>
          {topSchemas.map(([schema, count]) => (
            <div key={schema} style={{
              display: "flex", justifyContent: "space-between",
              fontSize: 11, marginBottom: 3,
            }}>
              <span style={{ color: MUTED, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "75%" }}>
                {schemaLabel(schema)}
              </span>
              <span style={{ color: TEXT, fontVariantNumeric: "tabular-nums" }}>
                {count.toLocaleString()}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function EnrichPanel({ feed }: { feed: TelemetryFeedEnrichment }) {
  const t = feed.today;
  return (
    <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16 }}>
      <CardHeader label="Spansh Enrichment Cache" status={feed.status} />
      <KV label="Total cached"      value={fmtNum(feed.total_cached)} />
      <Divider />
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 600, marginBottom: 6 }}>Today</div>
      {t ? (
        <>
          <KV label="Cache hits"    value={fmtNum(t.cache_hits)} />
          <KV label="Cache misses"  value={fmtNum(t.cache_misses)} />
          <KV label="Hit rate"      value={t.hit_rate_pct != null ? `${t.hit_rate_pct}%` : "—"} />
          <KV label="API calls"     value={fmtNum(t.api_calls)} />
          <KV label="API errors"    value={t.api_errors > 0 ? `⚠ ${t.api_errors}` : "0"} />
          <KV label="Avg fetch ms"  value={t.avg_fetch_ms != null ? `${t.avg_fetch_ms}ms` : "—"} />
          <KV label="Downloaded"    value={fmtBytes(t.bytes_fetched)} />
        </>
      ) : (
        <div style={{ fontSize: 12, color: MUTED }}>No requests today</div>
      )}
    </div>
  );
}

// ── Login wall ────────────────────────────────────────────────────────────────

function LoginWall({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
      });
      if (!res.ok) throw new Error("Invalid credentials");
      const data = await res.json();
      setAdminToken(data.access_token);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <div style={{ padding: "60px 24px", textAlign: "center", color: TEXT }}>
      <div style={{
        display: "inline-block", background: CARD, border: `1px solid ${BORDER}`,
        borderRadius: 10, padding: "32px 36px", maxWidth: 340, width: "100%", textAlign: "left",
      }}>
        <h3 style={{ margin: "0 0 20px", color: TEXT, fontSize: 16 }}>Sign in to view telemetry</h3>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, color: MUTED, marginBottom: 4 }}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
              style={{ width: "100%", padding: "7px 10px", background: BG, border: `1px solid ${BORDER}`, borderRadius: 5, color: TEXT, fontSize: 13, boxSizing: "border-box" }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 12, color: MUTED, marginBottom: 4 }}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
              style={{ width: "100%", padding: "7px 10px", background: BG, border: `1px solid ${BORDER}`, borderRadius: 5, color: TEXT, fontSize: 13, boxSizing: "border-box" }} />
          </div>
          {error && <p style={{ color: STATUS_COLOR.red, fontSize: 12, margin: "0 0 12px" }}>{error}</p>}
          <button type="submit" style={{
            width: "100%", padding: "9px 0", background: "#3b82d4", color: "#fff",
            border: "none", borderRadius: 5, fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>Sign In</button>
        </form>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TelemetryPage() {
  const [isAuthed, setIsAuthed] = useState(!!getAdminToken());
  const [data, setData] = useState<TelemetryStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);

  const fetchData = useCallback(() => {
    if (!getAdminToken()) return;
    setLoading(true);
    setError(null);
    getTelemetry()
      .then((d) => {
        setData(d);
        setLastFetched(new Date());
      })
      .catch((err) => {
        if (err?.status === 401 || (err instanceof Error && err.message.includes("401"))) {
          clearAdminToken();
          setIsAuthed(false);
        } else {
          setError(String(err));
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    if (!isAuthed) return;
    fetchData();
    const id = window.setInterval(fetchData, 60_000);
    return () => window.clearInterval(id);
  }, [isAuthed, fetchData]);

  if (!isAuthed) {
    return (
      <div style={{ background: BG, minHeight: "calc(100vh - 44px)", paddingTop: 44 }}>
        <LoginWall onLogin={() => { setIsAuthed(true); }} />
      </div>
    );
  }

  return (
    <div style={{
      background: BG, minHeight: "calc(100vh - 44px)",
      padding: "24px 20px", fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif',
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, maxWidth: 960, margin: "0 auto 20px" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: TEXT }}>📡 Feed Telemetry</h2>
          {lastFetched && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
              Updated {lastFetched.toLocaleTimeString()} · auto-refresh every 60s
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={fetchData}
            disabled={loading}
            style={{
              padding: "6px 14px", fontSize: 12, border: `1px solid ${BORDER}`,
              borderRadius: 5, background: loading ? "#21262d" : "#21262d",
              color: loading ? MUTED : TEXT, cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Refreshing…" : "⟳ Refresh"}
          </button>
          <button
            onClick={() => { clearAdminToken(); setIsAuthed(false); setData(null); }}
            style={{
              padding: "6px 14px", fontSize: 12, border: `1px solid ${BORDER}`,
              borderRadius: 5, background: "#21262d", color: MUTED, cursor: "pointer",
            }}
          >
            Sign Out
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          maxWidth: 960, margin: "0 auto 16px", padding: "10px 14px",
          background: "#2d1a1a", border: `1px solid ${STATUS_COLOR.red}`,
          borderRadius: 6, fontSize: 12, color: STATUS_COLOR.red,
        }}>
          Error: {error}
        </div>
      )}

      {/* Feed panels — 2×2 grid */}
      <div style={{
        maxWidth: 960, margin: "0 auto",
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
        gap: 16,
      }}>
        {data ? (
          <>
            <EddnPanel    feed={data.feeds.eddn_stream} />
            <IngestPanel  title="Spansh Batch Ingest" feed={data.feeds.spansh_ingest} />
            <IngestPanel  title="EDSM Sync"           feed={data.feeds.edsm_sync} />
            <EnrichPanel  feed={data.feeds.enrichment} />
          </>
        ) : loading ? (
          <div style={{ color: MUTED, fontSize: 13, padding: 20 }}>Loading telemetry…</div>
        ) : null}
      </div>
    </div>
  );
}
