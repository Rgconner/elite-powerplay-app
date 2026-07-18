/** Target Analysis API client. */

export interface TargetAnalysisItem {
  system_id64: number;
  system_name: string;
  controlling_power: string;
  power_state: string | null;
  control_progress: number | null;
  reinforcement: number | null;
  undermining: number | null;
  score: number;
  reasons: string[];
  distance_from_attacker: number | null;
  days_to_downgrade: number | null;
  trend: "worsening" | "improving" | "stable" | "unknown";
}

export interface TargetAnalysisResponse {
  targets: TargetAnalysisItem[];
  attacker_power: string;
  target_powers: string[];
}

export async function getTargetAnalysis(
  attackerPower: string,
  targetPowers: string[],
): Promise<TargetAnalysisResponse> {
  const res = await fetch("/api/powers/target-analysis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      attacker_power: attackerPower,
      target_powers: targetPowers,
    }),
  });
  if (!res.ok) throw new Error(`Target analysis failed (${res.status})`);
  return res.json() as Promise<TargetAnalysisResponse>;
}
