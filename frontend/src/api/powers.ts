/** Powers API client — typed fetch wrappers for Power Play endpoints. */

export interface PPSystemEntry {
  system_id64: number;
  name: string;
  x: number;
  y: number;
  z: number;
  allegiance: string | null;
  population: number | null;
  power: string | null;
  power_state: string | null;
  reinforcement: number | null;
  undermining: number | null;
  control_progress: number | null;
  snapshot_time: string | null;
  distance_from_center: number | null;
  /** undermining / reinforcement ratio 0.0–1.0; null if no data */
  undermine_ratio: number | null;
  /** Estimated CP merit decay this cycle (merits) */
  cp_decay: number | null;
}

export async function listPowers(): Promise<string[]> {
  const res = await fetch("/api/powers");
  if (!res.ok) throw new Error(`Powers list failed (${res.status})`);
  const data = await res.json() as { powers: string[] };
  return data.powers;
}

export async function searchPowers(q: string): Promise<string[]> {
  const res = await fetch(`/api/powers/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error(`Powers search failed (${res.status})`);
  const data = await res.json() as { powers: string[] };
  return data.powers;
}

export async function getPowerSystems(
  powerName: string,
  refSystemId64?: number,
): Promise<PPSystemEntry[]> {
  const params = new URLSearchParams();
  if (refSystemId64 != null) params.set("ref_id", String(refSystemId64));
  const qs = params.size > 0 ? `?${params.toString()}` : "";
  const res = await fetch(`/api/powers/${encodeURIComponent(powerName)}/systems${qs}`);
  if (!res.ok) throw new Error(`Get power systems failed (${res.status})`);
  return res.json() as Promise<PPSystemEntry[]>;
}
