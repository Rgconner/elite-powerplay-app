/** Contested Systems API client. */

export interface ConflictPowerProgress {
  power: string;
  progress: number;
}

export interface ContestedSystemInfo {
  system_id64: number;
  system_name: string;
  /** "Multiple" or first power name */
  controlling_power: string;
  power_state: string;
  control_progress: number | null;
  reinforcement: number | null;
  undermining: number | null;
  /** Distance (LY) from the nearest system owned by the queried power */
  distance_from_power: number | null;
  x: number | null;
  y: number | null;
  z: number | null;
  /** Comma-separated contesting powers e.g. "A. Lavigny-Duval,Aisling Duval" */
  powers_list: string | null;
  /** JSON string: [{power, progress}, ...] from power_conflict_progress */
  conflict_progress: string | null;
}

/** Parse the conflict_progress JSON string safely */
export function parseConflictProgress(item: ContestedSystemInfo): ConflictPowerProgress[] {
  if (!item.conflict_progress) return [];
  try {
    return JSON.parse(item.conflict_progress) as ConflictPowerProgress[];
  } catch {
    return [];
  }
}

export async function getContestedSystems(
  powerName: string,
): Promise<ContestedSystemInfo[]> {
  const res = await fetch(
    `/api/powers/${encodeURIComponent(powerName)}/contested`,
  );
  if (!res.ok) throw new Error(`Get contested systems failed (${res.status})`);
  return res.json() as Promise<ContestedSystemInfo[]>;
}
