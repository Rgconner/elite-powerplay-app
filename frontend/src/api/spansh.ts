/** Spansh enrichment API client — PLAT/BOOM/PRISTINE data. */

export interface SpanshEnrichment {
  has_platinum: boolean;
  has_boom: boolean;
  has_pristine: boolean;
}

export interface BatchEnrichResponse {
  results: Record<number, SpanshEnrichment>;
}

/**
 * Fetch cached PLAT/BOOM/PRISTINE enrichment for one or more system IDs.
 * Missing data is fetched from Spansh on the server side and cached
 * persistently (no TTL — data is pulled on first access and kept).
 *
 * @param systemIds  Array of system_id64 values to enrich
 * @param forceRefresh  If true, bypass the cache and re-fetch from Spansh.
 *                      Use after deploying detection fixes.
 */
export async function getSpanshEnrichmentBatch(
  systemIds: number[],
  forceRefresh: boolean = false,
): Promise<Record<number, SpanshEnrichment>> {
  if (systemIds.length === 0) return {};

  const res = await fetch("/api/spansh/enrich/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ system_ids: systemIds, force_refresh: forceRefresh }),
  });
  if (!res.ok) {
    throw new Error(`Spansh enrichment batch failed (${res.status})`);
  }
  const data = (await res.json()) as BatchEnrichResponse;
  return data.results;
}

/**
 * Clear all cached Spansh enrichment data on the server.  Admin-only.
 * The next batch request will re-fetch fresh data from Spansh.
 */
export async function clearEnrichmentCache(): Promise<{ deleted: number }> {
  const { getAuthHeader } = await import("./admin");
  const res = await fetch("/api/spansh/enrich/cache", {
    method: "DELETE",
    headers: getAuthHeader(),
  });
  if (!res.ok) {
    throw new Error(`Clear enrichment cache failed (${res.status})`);
  }
  return res.json() as Promise<{ deleted: number }>;
}

export interface ValidateMismatch {
  system_id64: number;
  system_name: string | null;
  field: string;
  cached: boolean;
  live: boolean;
}

export interface ValidateResponse {
  total_checked: number;
  mismatches_found: number;
  mismatches: ValidateMismatch[];
}

/**
 * Validate all cached enrichment entries against live Spansh data.
 * Mismatches are auto-corrected in the database. Admin-only.
 */
export async function validateEnrichment(): Promise<ValidateResponse> {
  const { getAuthHeader } = await import("./admin");
  const res = await fetch("/api/spansh/enrich/validate", {
    method: "POST",
    headers: getAuthHeader(),
  });
  if (!res.ok) {
    throw new Error(`Validate enrichment failed (${res.status})`);
  }
  return res.json() as Promise<ValidateResponse>;
}

export interface EnrichStatus {
  total_cached: number;
}

/**
 * Get enrichment cache stats. Admin-only.
 */
export async function getEnrichStatus(): Promise<EnrichStatus> {
  const res = await fetch("/api/spansh/enrich/status");
  if (!res.ok) {
    throw new Error(`Enrich status failed (${res.status})`);
  }
  return res.json() as Promise<EnrichStatus>;
}