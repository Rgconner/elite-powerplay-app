/** Factions API client — typed fetch wrappers for all factions endpoints. */

import { handleFetchError } from "./errors";

// ---------------------------------------------------------------------------
// Types (mirror Pydantic schemas exactly)
// ---------------------------------------------------------------------------

export interface FactionListItem {
  id: number;
  name: string;
  allegiance: string | null;
  government: string | null;
  system_count: number;
}

export interface PaginatedFactions {
  total: number;
  page: number;
  limit: number;
  items: FactionListItem[];
}

export interface FactionSystemEntry {
  system_name: string;
  system_id64: number;
  is_controlling: boolean;
  x: number;
  y: number;
  z: number;
  pp_state: string | null;
  pp_power: string | null;
  /** 0.0–1.0 — multiply by 100 to display as a percentage */
  influence: number | null;
  /** Euclidean LY distance from the selected center system (null if not requested) */
  distance_from_center: number | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function listFactions(
  page = 1,
  limit = 50,
): Promise<PaginatedFactions> {
  const res = await fetch(`/api/factions?page=${page}&limit=${limit}`);
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<PaginatedFactions>;
}

export async function searchFactions(q: string): Promise<FactionListItem[]> {
  const res = await fetch(
    `/api/factions/search?q=${encodeURIComponent(q)}`,
  );
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<FactionListItem[]>;
}

export async function getPowers(): Promise<string[]> {
  const res = await fetch("/api/factions/powers");
  if (!res.ok) await handleFetchError(res);
  const data = await res.json() as { powers: string[] };
  return data.powers;
}

export async function getFactionSystems(
  factionName: string,
  centerSystemId64?: number,
): Promise<FactionSystemEntry[]> {
  const params = new URLSearchParams();
  if (centerSystemId64 != null) {
    params.set("center_id", String(centerSystemId64));
  }
  const qs = params.size > 0 ? `?${params.toString()}` : "";
  const res = await fetch(
    `/api/factions/${encodeURIComponent(factionName)}/systems${qs}`,
  );
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<FactionSystemEntry[]>;
}
