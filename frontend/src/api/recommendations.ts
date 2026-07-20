/** Recommendations API client. */

export interface RecommendationItem {
  system_id64: number;
  system_name: string;
  score: number;
  type: "fortify" | "expand";
  reasons: string[];
  power_state: string | null;
  reinforcement: number | null;
  undermining: number | null;
  undermine_ratio: number | null;
  /** Normalized 0.0–1.0+ progress toward next state; <0 = failing now; ≥1 = upgrade ready */
  control_progress: number | null;
  /** Estimated days until state downgrade = progress × 7; 0 = failing now; null = not at risk */
  days_to_failure: number | null;
  distance_from_center: number | null;
  threat_trend: "worsening" | "improving" | "stable" | "unknown";
  // ── Absolute merit context (thresholds: Acquire=120k, Fortified=333k, Stronghold=667k) ──
  /** Absolute merit position on the 0→667,000 scale */
  merit_position: number | null;
  /** Merits above downgrade threshold — cushion remaining */
  buffer_merits: number | null;
  /** Additional merits needed to reach 50% progress (safe zone) */
  merits_to_safety: number | null;
  /** Additional merits needed to reach 100% (next state upgrade) */
  merits_to_upgrade: number | null;
  /** For expand items: "fortified" | "stronghold" | "both" | "expansion" — which anchor qualifies it */
  anchor_type: string | null;
  /** For expand items: JSON string [{power, progress}, ...] — per-power conflict progress.
   *  Same format as ContestedSystemInfo.conflict_progress. Null for Unoccupied systems
   *  with no conflict data. */
  conflict_progress: string | null;
}

export interface RecommendationsResponse {
  fortify: RecommendationItem[];
  expand: RecommendationItem[];
  llm_summary: string | null;
}

export async function getRecommendations(
  powerName: string,
  refSystemId64?: number,
): Promise<RecommendationsResponse> {
  const params = new URLSearchParams();
  if (refSystemId64 != null) params.set("ref_id", String(refSystemId64));
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(
    `/api/powers/${encodeURIComponent(powerName)}/recommendations${qs}`
  );
  if (!res.ok) throw new Error(`Get recommendations failed (${res.status})`);
  return res.json() as Promise<RecommendationsResponse>;
}
