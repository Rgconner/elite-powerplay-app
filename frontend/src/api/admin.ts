/** Admin API client. */

import { handleFetchError } from "./errors";

const TOKEN_KEY = "pp_admin_token";

export function getAdminToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAdminToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** Returns Authorization header object for admin-authenticated requests. */
export function getAuthHeader(): HeadersInit {
  const token = getAdminToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function adminLogin(
  email: string,
  password: string
): Promise<TokenResponse> {
  // Backend uses OAuth2 form convention: username + password as form-urlencoded
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<TokenResponse>;
}

export interface IngestionRunRecord {
  id: number;
  source: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  records_processed: number;
}

export interface AdminSettingRecord {
  id: number;
  key: string;
  value: string;
}

export async function getAdminStatus(): Promise<{
  recent_runs: IngestionRunRecord[];
  spansh_next_run: string | null;
  edsm_next_run: string | null;
}> {
  const res = await fetch("/api/admin/status", { headers: getAuthHeader() });
  if (!res.ok) await handleFetchError(res);
  return res.json();
}

export async function triggerSpanshIngest(): Promise<void> {
  const res = await fetch("/api/admin/ingest/spansh", {
    method: "POST",
    headers: getAuthHeader(),
  });
  if (!res.ok) await handleFetchError(res);
}

export async function triggerEdsmSync(): Promise<void> {
  const res = await fetch("/api/admin/ingest/edsm", {
    method: "POST",
    headers: getAuthHeader(),
  });
  if (!res.ok) await handleFetchError(res);
}

export async function getSettings(): Promise<AdminSettingRecord[]> {
  const res = await fetch("/api/admin/settings", { headers: getAuthHeader() });
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<AdminSettingRecord[]>;
}

export async function updateSettings(
  updates: Record<string, string>
): Promise<void> {
  // Backend expects list[{key, value}] not a plain object
  const payload = Object.entries(updates).map(([key, value]) => ({ key, value }));
  const res = await fetch("/api/admin/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) await handleFetchError(res);
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string,
): Promise<void> {
  const res = await fetch("/api/admin/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({
      current_password:  currentPassword,
      new_password:      newPassword,
      confirm_password:  confirmPassword,
    }),
  });
  if (!res.ok) await handleFetchError(res);
}

// ── Telemetry types & fetch ───────────────────────────────────────────────────

export interface TelemetryRunSummary {
  id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  records_processed: number;
  duration_seconds: number | null;
  api_calls_made: number;
  api_errors: number;
  error_count: number;
  error_detail: string | null;
  bytes_downloaded: number;
  pages_fetched: number;
}

export interface TelemetryFeedIngest {
  status: "green" | "yellow" | "red";
  last_run: TelemetryRunSummary | null;
  history: TelemetryRunSummary[];
  next_run_at: string | null;
  interval_hours: number;
}

export interface TelemetryFeedEddn {
  status: "green" | "yellow" | "red";
  recorded_at: string | null;
  listener_started_at: string | null;
  events_total: number;
  events_last_5min: number;
  dedup_rejected: number;
  decode_errors: number;
  last_event_ts: string | null;
  // Extended throughput metrics
  messages_received_total: number;
  bytes_received_total: number;
  skipped_schema_total: number;
  skipped_event_total: number;
  messages_per_min: number | null;
  top_schemas: Record<string, number>;
}

export interface TelemetryFeedEnrichment {
  status: "green" | "yellow" | "red";
  total_cached: number;
  today: {
    cache_hits: number;
    cache_misses: number;
    hit_rate_pct: number | null;
    api_calls: number;
    api_errors: number;
    avg_fetch_ms: number | null;
    bytes_fetched: number;
  } | null;
}

export interface TelemetryStatus {
  generated_at: string;
  feeds: {
    spansh_ingest: TelemetryFeedIngest;
    edsm_sync:     TelemetryFeedIngest;
    eddn_stream:   TelemetryFeedEddn;
    enrichment:    TelemetryFeedEnrichment;
  };
}

export async function getTelemetry(): Promise<TelemetryStatus> {
  const res = await fetch("/api/telemetry", { headers: getAuthHeader() });
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<TelemetryStatus>;
}

// ── Runtime health (backend services/health_monitor.py) ──────────────────────

export interface RuntimeAlert {
  fingerprint: string;
  tier: "immediate" | "investigate" | "monitor";
  urgency_label: string;
  message: string;
  src_ip: string | null;
  scored_at: string;
}

export interface RuntimeHealth {
  uptime_s: number;
  loop_lag_s: number;
  max_loop_lag_s: number;
  loop_stalls: number;
  throttled_requests: number;
  in_flight: number;
  busiest_clients: { client_ip: string; endpoint: string; requests_per_min: number }[];
  slowest_endpoints: { endpoint: string; p95_s: number; samples: number }[];
  recent_alerts: RuntimeAlert[];
  limits: { loop_stall_s: number; client_rate_per_min: number; slow_p95_s: number; alerts_to: string | null };
}

export async function getRuntimeHealth(): Promise<RuntimeHealth> {
  const res = await fetch("/api/telemetry/health", { headers: getAuthHeader() });
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<RuntimeHealth>;
}
