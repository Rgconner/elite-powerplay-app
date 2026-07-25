/** Systems API client. */

import { handleFetchError } from "./errors";

export interface SystemSearchResult {
  system_id64: number;
  name: string;
  x: number | null;
  y: number | null;
  z: number | null;
}

export async function searchSystems(q: string): Promise<SystemSearchResult[]> {
  const res = await fetch(`/api/systems/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<SystemSearchResult[]>;
}
