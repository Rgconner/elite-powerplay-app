/** Power Play cycle helpers. Cycles reset every Thursday at 07:00 UTC. */

export function getLastCycleReset(now: Date = new Date()): Date {
  // Thursday = day 4 (0=Sun)
  const day = now.getUTCDay();
  const daysSinceThurs = (day + 7 - 4) % 7;
  const resetDate = new Date(Date.UTC(
    now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - daysSinceThurs, 7, 0, 0
  ));
  // If reset is in the future (before 07:00 on Thursday), step back one week
  if (resetDate > now) {
    resetDate.setUTCDate(resetDate.getUTCDate() - 7);
  }
  return resetDate;
}

/**
 * True if the game data was observed before this cycle's reset, so its
 * reinforcement / undermining belong to the previous cycle (they reset to
 * zero at the tick).  Takes the backend's naive-UTC spansh_updated_at.
 */
export function isPriorCycle(observedAt: string | null | undefined): boolean {
  if (!observedAt) return false;
  const t = new Date(observedAt.endsWith("Z") ? observedAt : observedAt + "Z").getTime();
  if (isNaN(t)) return false;
  return t < getLastCycleReset().getTime();
}
