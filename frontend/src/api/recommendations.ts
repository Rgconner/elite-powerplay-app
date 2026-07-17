/** Recommendations API client. */

export interface RecommendationItem {
  system_name: string;
  system_id64: number;
  score: number;
  type: "fortify" | "expand";
  reasons: string[];
  distance_from_center: number | null;
  pp_state: string | null;
  influence: number | null;
  influence_trend: "rising" | "falling" | "stable" | "unknown";
}

export interface RecommendationsResponse {
  fortify: RecommendationItem[];
  expand: RecommendationItem[];
  llm_summary: string | null;
}

export async function getRecommendations(
  factionName: string,
  centerSystemId64?: number
): Promise<RecommendationsResponse> {
  const params = new URLSearchParams();
  if (centerSystemId64 != null) {
    params.set("center_id", String(centerSystemId64));
  }
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(
    `/api/factions/${encodeURIComponent(factionName)}/recommendations${qs}`
  );
  if (!res.ok) throw new Error(`Get recommendations failed (${res.status})`);
  return res.json() as Promise<RecommendationsResponse>;
}
