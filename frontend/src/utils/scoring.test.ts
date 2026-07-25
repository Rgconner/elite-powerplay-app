/**
 * Unit tests for computeTargetScore (scoring.ts).
 *
 * Tests are pure: no network, no DOM, no React.
 * Run with: npm test  (vitest run)
 */

import { describe, it, expect } from "vitest";
import { computeTargetScore, SCORE_WEIGHTS } from "./scoring";

// ─── helpers ────────────────────────────────────────────────────────────────

/** Build a minimal params object with sensible defaults; override what you need. */
function params(overrides: {
  control_progress?: number | null;
  power_state?: string | null;
  distance_ly?: number | null;
  reinforcement?: number | null;
  undermining?: number | null;
}) {
  return {
    control_progress: null,
    power_state: null,
    distance_ly: null,
    reinforcement: null,
    undermining: null,
    ...overrides,
  };
}

// ─── Progress component ──────────────────────────────────────────────────────

describe("computeTargetScore — progress component", () => {
  it("returns 0 progress points when control_progress is 0", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    // distance 999 LY → 0 distance pts; no threat → 0 threat pts; progress 0 → 0 pts
    expect(score).toBe(0);
  });

  it("awards PROGRESS_MAX points when control_progress is 1.0", () => {
    const score = computeTargetScore(
      params({ control_progress: 1.0, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    // Only progress component fires: 1.0 × 50 = 50
    expect(score).toBe(SCORE_WEIGHTS.PROGRESS_MAX);
  });

  it("awards proportional progress points at 50% progress", () => {
    const score = computeTargetScore(
      params({ control_progress: 0.5, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(SCORE_WEIGHTS.PROGRESS_MAX * 0.5);
  });

  it("clamps progress > 1.0 to PROGRESS_MAX", () => {
    const score = computeTargetScore(
      params({ control_progress: 2.0, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    // Progress clamped to 1: contributes at most PROGRESS_MAX
    expect(score).toBe(SCORE_WEIGHTS.PROGRESS_MAX);
  });

  it("treats null control_progress as 0", () => {
    const withNull = computeTargetScore(
      params({ control_progress: null, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    const withZero = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    expect(withNull).toBe(withZero);
  });
});

// ─── Distance component ──────────────────────────────────────────────────────

describe("computeTargetScore — distance component", () => {
  it("awards DISTANCE_MAX points at 0 LY", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 0, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(SCORE_WEIGHTS.DISTANCE_MAX);
  });

  it("awards 0 distance points at DISTANCE_FALLOFF_LY", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: SCORE_WEIGHTS.DISTANCE_FALLOFF_LY, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(0);
  });

  it("awards 0 distance points beyond DISTANCE_FALLOFF_LY", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: SCORE_WEIGHTS.DISTANCE_FALLOFF_LY + 50, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(0);
  });

  it("awards half DISTANCE_MAX at half the falloff distance", () => {
    const halfDist = SCORE_WEIGHTS.DISTANCE_FALLOFF_LY / 2;
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: halfDist, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(SCORE_WEIGHTS.DISTANCE_MAX / 2);
  });
});

// ─── Threat component ────────────────────────────────────────────────────────

describe("computeTargetScore — threat component", () => {
  it("awards 0 threat points when reinforcement >= undermining (healthy system)", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 5000, undermining: 1000 }),
    );
    expect(score).toBe(0);
  });

  it("awards 0 threat points when both reinforcement and undermining are 0", () => {
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 0, undermining: 0 }),
    );
    expect(score).toBe(0);
  });

  it("awards THREAT_MAX when net undermining equals THREAT_THRESHOLD_MERITS", () => {
    const u = SCORE_WEIGHTS.THREAT_THRESHOLD_MERITS;
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 0, undermining: u }),
    );
    expect(score).toBe(SCORE_WEIGHTS.THREAT_MAX);
  });

  it("caps threat at THREAT_MAX when net undermining exceeds THREAT_THRESHOLD_MERITS", () => {
    const u = SCORE_WEIGHTS.THREAT_THRESHOLD_MERITS * 5;
    const score = computeTargetScore(
      params({ control_progress: 0, distance_ly: 999, reinforcement: 0, undermining: u }),
    );
    expect(score).toBe(SCORE_WEIGHTS.THREAT_MAX);
  });
});

// ─── Combined cases ──────────────────────────────────────────────────────────

describe("computeTargetScore — combined", () => {
  it("score is always >= 0 for any combination of inputs", () => {
    const cases = [
      params({ control_progress: 0, distance_ly: 0, reinforcement: 0, undermining: 0 }),
      params({ control_progress: 1, distance_ly: 0, reinforcement: 0, undermining: 0 }),
      params({ control_progress: 0, distance_ly: 0, reinforcement: 9999, undermining: 0 }),
      params({ control_progress: null, distance_ly: null, reinforcement: null, undermining: null }),
      params({ control_progress: -1, distance_ly: -50, reinforcement: -100, undermining: -100 }),
    ];
    for (const c of cases) {
      expect(computeTargetScore(c)).toBeGreaterThanOrEqual(0);
    }
  });

  it("max score with all components maxed out is capped at 100", () => {
    // progress=1 → 50, distance=0 → 30, threat saturated → 20; total = 100
    const score = computeTargetScore(
      params({
        control_progress: 1.0,
        distance_ly: 0,
        reinforcement: 0,
        undermining: SCORE_WEIGHTS.THREAT_THRESHOLD_MERITS,
      }),
    );
    expect(score).toBe(100);
  });

  it("typical case: 60% progress, 30 LY, partial threat", () => {
    // progressScore = 0.6 × 50 = 30
    // distanceScore = 30 × (1 - 30/100) = 30 × 0.7 = 21
    // threatScore: net = 500 - 0 = 500; 500/1000 × 20 = 10
    // total = 61 → clamped to 61
    const score = computeTargetScore(
      params({ control_progress: 0.6, distance_ly: 30, reinforcement: 0, undermining: 500 }),
    );
    expect(score).toBe(61);
  });

  it("power_state is accepted but does not affect the score", () => {
    const base = params({ control_progress: 0.5, distance_ly: 50, reinforcement: 0, undermining: 500 });
    const withState = { ...base, power_state: "Fortified" };
    expect(computeTargetScore(withState)).toBe(computeTargetScore(base));
  });
});
