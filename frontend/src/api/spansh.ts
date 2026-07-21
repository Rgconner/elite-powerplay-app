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
 */
export async function getSpanshEnrichmentBatch(
  systemIds: number[],
): Promise<Record<number, SpanshEnrichment>> {
  if (systemIds.length === 0) return {};

  const res = await fetch("/api/spansh/enrich/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ system_ids: systemIds }),
  });
  if (!res.ok) {
    throw new Error(`Spansh enrichment batch failed (${res.status})`);
  }
  const data = (await res.json()) as BatchEnrichResponse;
  return data.results;
}