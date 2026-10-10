/** Contested Systems API client. */

import { handleFetchError } from "./errors";

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
  /** ISO datetime string — when Spansh last received game data for this system */
  spansh_updated_at: string | null;
}

/** Returns a human-readable age string e.g. "3h ago", "2d ago" */
export function formatDataAge(spansh_updated_at: string | null): string {
  if (!spansh_updated_at) return "unknown age";
  const ms = Date.now() - new Date(spansh_updated_at + "Z").getTime();
  const h  = Math.floor(ms / 3_600_000);
  const d  = Math.floor(h / 24);
  if (d > 0)  return `${d}d ago`;
  if (h > 0)  return `${h}h ago`;
  const m = Math.floor(ms / 60_000);
  return `${m}m ago`;
}

/**
 * Returns true if data is older than maxHours.
 *
 * @param nullIsStale - Controls how a null timestamp is treated.
 *   true  (default / spec-correct): NULL timestamp → unknown age → treat as stale.
 *   false (legacy / test mode):     NULL timestamp → keep the row (pre-migration behaviour).
 *   Matches the 'contested_null_ts_is_stale' admin setting.
 */
export function isStale(
  spansh_updated_at: string | null,
  maxHours = 24,
  nullIsStale = true,
): boolean {
  if (!spansh_updated_at) return nullIsStale;
  const ms = Date.now() - new Date(spansh_updated_at + "Z").getTime();
  return ms > maxHours * 3_600_000;
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

/** Control points per 1.0 of conflict progress (the acquisition threshold). */
export const ACQUIRE_CP = 120_000;

export interface ConflictStanding extends ConflictPowerProgress {
  /** Control points: progress × 120,000. */
  cp: number;
  /** Share of the leader's points, 0–1 (leader = 1). */
  relative: number;
  /** Points behind the leader (0 for the leader). */
  gapCp: number;
  isLeader: boolean;
}

/**
 * Rank a contested system's powers against the current leader.  The race is
 * won by whoever has the most points at cycle end, so the leader is the
 * reference (100%) and everyone else is shown as a share of the leader.
 */
export function rankConflict(entries: ConflictPowerProgress[]): ConflictStanding[] {
  const ranked = [...entries].sort((a, b) => b.progress - a.progress);
  const top = ranked[0]?.progress ?? 0;
  return ranked.map((e, i) => ({
    ...e,
    cp: Math.round(e.progress * ACQUIRE_CP),
    relative: top > 0 ? Math.max(0, e.progress) / top : 0,
    gapCp: Math.round((top - e.progress) * ACQUIRE_CP),
    isLeader: i === 0 && top > 0,
  }));
}

export async function getContestedSystems(
  powerName: string,
): Promise<ContestedSystemInfo[]> {
  const res = await fetch(
    `/api/powers/${encodeURIComponent(powerName)}/contested`,
  );
  if (!res.ok) await handleFetchError(res);
  return res.json() as Promise<ContestedSystemInfo[]>;
}
