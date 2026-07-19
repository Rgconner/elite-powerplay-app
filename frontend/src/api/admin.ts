/** Admin API client. */

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
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `Login failed (${res.status})`);
  }
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
  if (!res.ok) throw new Error(`Failed to load admin status (${res.status})`);
  return res.json();
}

export async function triggerSpanshIngest(): Promise<void> {
  const res = await fetch("/api/admin/ingest/spansh", {
    method: "POST",
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Spansh ingest trigger failed (${res.status})`);
}

export async function triggerEdsmSync(): Promise<void> {
  const res = await fetch("/api/admin/ingest/edsm", {
    method: "POST",
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`EDSM sync trigger failed (${res.status})`);
}

export async function getSettings(): Promise<AdminSettingRecord[]> {
  const res = await fetch("/api/admin/settings", { headers: getAuthHeader() });
  if (!res.ok) throw new Error(`Failed to load settings (${res.status})`);
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
  if (!res.ok) throw new Error(`Failed to update settings (${res.status})`);
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
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    // Pydantic validation errors come back as an array under "detail"
    const detail = (data as { detail?: unknown }).detail;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((e: { msg?: string }) => e.msg ?? String(e)).join(" · "));
    }
    throw new Error(typeof detail === "string" ? detail : `Change password failed (${res.status})`);
  }
}
