/** Spansh enrichment API client — PLAT/BOOM data. */

export interface SpanshEnrichment {
  has_platinum: boolean;
  has_boom: boolean;
}

export interface BatchEnrichResponse {
  results: Record<number, SpanshEnrichment>;
}

/**
 * Fetch cached PLAT/BOOM enrichment for one or more system IDs.
 * Missing/stale data is fetched from Spansh on the server side and cached for 12h.
 *
 * @param systemIds  Array of system_id64 values to enrich
 * @param forceRefresh  If true, bypass the cache and re-fetch from Spansh.
 *                      Use after deploying platinum-detection fixes.
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
 * Clear all cached Spansh enrichment data on the server.
 * The next batch request will re-fetch fresh data from Spansh.
 */
export async function clearEnrichmentCache(): Promise<{ deleted: number }> {
  const res = await fetch("/api/spansh/enrich/cache", { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Clear enrichment cache failed (${res.status})`);
  }
  return res.json() as Promise<{ deleted: number }>;
}
