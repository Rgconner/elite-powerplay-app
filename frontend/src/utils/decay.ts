/** Merit decay utility functions for PP2.0 CP decay mechanic. */

/**
 * Compute effective undermining after applying CP decay.
 *
 * The game's reported undermining value includes merit decay that has
 * already happened but isn't broken out. We estimate the decay amount
 * and subtract it to get the "active" undermining.
 *
 * Net = Reinforcement − Effective_Undermining
 *     = R − (U − cp_decay)
 *     = R − U + cp_decay
 */
export function effectiveUndermining(
  undermining: number | null,
  cpDecay: number | null,
): number {
  const u = undermining ?? 0;
  const d = cpDecay ?? 0;
  return Math.max(0, u - d);
}

/**
 * Compute Net (Reinforcement minus Effective Undermining).
 *
 * When cp_decay is present, Net = R − (U − cp_decay).
 * Otherwise falls back to simple R − U.
 */
export function netValue(
  reinforcement: number | null,
  undermining: number | null,
  cpDecay: number | null,
): number {
  const r = reinforcement ?? 0;
  const effU = effectiveUndermining(undermining, cpDecay);
  return r - effU;
}