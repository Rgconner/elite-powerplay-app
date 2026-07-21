/** Scoring utilities for the Target List tab. */

// ── Merit thresholds per state (mirrors backend constants) ─────────────────
export const MERIT_ACQUIRE   = 120_000;  // Exploited → Fortified
export const MERIT_FORTIFIED = 333_000;  // Fortified → Stronghold
export const MERIT_STRONGHOLD= 667_000;  // Stronghold → next

const BAND_EXPLOITED  = MERIT_FORTIFIED - MERIT_ACQUIRE;   // 213_000
const BAND_FORTIFIED  = MERIT_STRONGHOLD - MERIT_FORTIFIED; // 334_000
const BAND_STRONGHOLD = MERIT_STRONGHOLD - MERIT_FORTIFIED; // proxy

/** Return (merits earned, merits needed for next state) given state and progress. */
export function meritsToNextState(
  state: string | null,
  progress: number,
): { meritsEarned: number; meritsNeeded: number; meritsRemaining: number } {
  const lower = state === "Stronghold" ? MERIT_STRONGHOLD
               : state === "Fortified"  ? MERIT_FORTIFIED
               : MERIT_ACQUIRE;
  const band  = state === "Stronghold" ? BAND_STRONGHOLD
               : state === "Fortified"  ? BAND_FORTIFIED
               : BAND_EXPLOITED;
  const meritsEarned  = Math.round(lower + Math.max(0, progress) * band);
  const meritsNeeded  = lower + band;
  const meritsRemaining = Math.max(0, meritsNeeded - meritsEarned);
  return { meritsEarned, meritsNeeded, meritsRemaining };
}

/** State label for display */
export const PP_STATE_LABELS: Record<string, string> = {
  Stronghold:   "Stronghold",
  Fortified:    "Fortified",
  Exploited:    "Exploited",
  Unoccupied:   "Unoccupied",
  Contested:    "Contested",
  Turmoil:      "Turmoil",
  Undermined:   "Undermined",
  Expansion:    "Expansion",
  InPrepareRadius: "In Prep Radius",
  Prepared:     "Prepared",
  HomeSystem:   "Home System",
};

/**
 * Compute a target priority score for a system in the Target List.
 *
 * Factors:
 *   1. Control progress (higher = better) – up to 50 pts per 100%
 *   2. Distance from reference (closer = better) – up to 30 pts when ≤100 LY
 *   3. Merit progress toward next state (higher = better) – up to 20 pts
 *
 * Score range: 0–100+ (progress can exceed 100% giving scores > 100)
 */
export function computeTargetScore(params: {
  control_progress: number | null;
  power_state: string | null;
  distance_ly: number | null;
}): number {
  const { control_progress, power_state, distance_ly } = params;

  // 1. Progress component (0–50+)
  const progress = control_progress ?? 0;
  const progressScore = Math.max(0, progress * 50);

  // 2. Distance component (0–30)
  const dist = distance_ly ?? 999;
  const distanceScore = Math.max(0, 30 * (1 - Math.min(1, dist / 100)));

  // 3. Merit completeness component (0–20)
  const { meritsEarned, meritsNeeded } = meritsToNextState(power_state, progress);
  const meritRatio = meritsNeeded > 0 ? Math.min(1, meritsEarned / meritsNeeded) : 0;
  const meritScore = meritRatio * 20;

  return Math.round((progressScore + distanceScore + meritScore) * 10) / 10;
}