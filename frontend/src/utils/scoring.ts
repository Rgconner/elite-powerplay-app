/** Scoring utilities for the Target List tab. */

// ── Merit thresholds per state (mirrors backend constants) ─────────────────
export const MERIT_ACQUIRE   = 120_000;  // Unoccupied → Exploited (acquisition)
export const MERIT_FORTIFIED = 333_000;  // Exploited → Fortified
export const MERIT_STRONGHOLD= 667_000;  // Fortified → Stronghold

const BAND_UNOCCUPIED = MERIT_ACQUIRE;                        // 120_000 (0 → 120k)
const BAND_EXPLOITED  = MERIT_FORTIFIED - MERIT_ACQUIRE;      // 213_000
const BAND_FORTIFIED  = MERIT_STRONGHOLD - MERIT_FORTIFIED;   // 334_000
const BAND_STRONGHOLD = MERIT_STRONGHOLD - MERIT_FORTIFIED;   // proxy (open-ended)

/** Return (merits earned, merits needed for next state) given state and progress.
 *
 *  State           Lower threshold   Band width    Next state
 *  ─────────────   ───────────────   ───────────   ──────────
 *  Unoccupied/null 0                 120,000       Exploited
 *  Exploited       120,000           213,000       Fortified
 *  Fortified       333,000           334,000       Stronghold
 *  Stronghold      667,000           334,000       (open-ended)
 */
export function meritsToNextState(
  state: string | null,
  progress: number,
): { meritsEarned: number; meritsNeeded: number; meritsRemaining: number } {
  const lower = state === "Stronghold" ? MERIT_STRONGHOLD
               : state === "Fortified"  ? MERIT_FORTIFIED
               : state === "Exploited"  ? MERIT_ACQUIRE
               : 0;  // Unoccupied or null — acquisition starts at 0
  const band  = state === "Stronghold" ? BAND_STRONGHOLD
               : state === "Fortified"  ? BAND_FORTIFIED
               : state === "Exploited"  ? BAND_EXPLOITED
               : BAND_UNOCCUPIED;  // Unoccupied: 0 → 120,000
  const meritsEarned  = Math.round(lower + Math.max(0, progress) * band);
  const meritsNeeded  = lower + band;
  const meritsRemaining = Math.max(0, meritsNeeded - meritsEarned);
  return { meritsEarned, meritsNeeded, meritsRemaining };
}

/**
 * Merits needed to reach 25% control progress (safe threshold).
 * Returns null if already at or above 25%.
 */
export function meritsToSafety(
  power_state: string | null,
  control_progress: number | null,
): number | null {
  if (control_progress == null || control_progress >= 0.25) return null;
  const current = meritsToNextState(power_state, control_progress);
  const safe    = meritsToNextState(power_state, 0.25);
  return Math.max(0, safe.meritsEarned - current.meritsEarned);
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
 *   2. Distance from reference (closer = better) – up to 30 pts (linear decay
 *      from 30 at 0 LY to 0 at 100 LY)
 *   3. Undermining threat (higher net undermining = needs more help) – up to 20 pts
 *
 * The threat component replaces the previous merit-completeness factor, which
 * was redundant with the progress component (both derived from control_progress).
 * Using reinforcement/undermining gives an independent signal: a system under
 * active attack scores higher for fortification priority, even if its progress
 * is currently healthy.
 *
 * Score range: 0–100 (capped). Progress > 1.0 can push the raw score above 100,
 * but it is clamped so the MAX badge tier is reachable only by threatened
 * systems that are also close to the reference.
 */
export function computeTargetScore(params: {
  control_progress: number | null;
  power_state: string | null;
  distance_ly: number | null;
  reinforcement: number | null;
  undermining: number | null;
}): number {
  const { control_progress, distance_ly, reinforcement, undermining } = params;
  // Note: power_state is accepted in the params interface for API stability
  // and future use, but is not currently used in the score calculation.

  // 1. Progress component (0–50)
  const progress = control_progress ?? 0;
  const progressScore = Math.max(0, Math.min(1, progress)) * 50;

  // 2. Distance component (0–30) — linear decay: 30 at 0 LY → 0 at 100 LY
  const dist = distance_ly ?? 999;
  const distanceScore = Math.max(0, 30 * (1 - Math.min(1, dist / 100)));

  // 3. Undermining threat component (0–20)
  //    Net undermining (U − R) indicates how much the system is losing ground
  //    this cycle. We normalise against a reference of 1000 net merits so that
  //    typical small deficits get partial credit and large deficits max out.
  //    Systems with R >= U (healthy) get 0 threat points.
  const r = reinforcement ?? 0;
  const u = undermining ?? 0;
  const netLoss = Math.max(0, u - r);  // only positive losses count
  const threatScore = Math.min(1, netLoss / 1000) * 20;

  const raw = progressScore + distanceScore + threatScore;
  return Math.round(Math.min(100, raw) * 10) / 10;
}
