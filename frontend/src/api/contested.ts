/** Contested Systems API client. */

export interface ContestedSystemInfo {
  system_id64: number;
  system_name: string;
  /** The power whose snapshot record carries power_state='Contested' */
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
