"""Unit tests for backend/services/decay.py.

Only pure calculation functions are imported — no database, no FastAPI.
Run with: pytest  (from the backend/ directory)
"""

import pytest
from services.decay import (
    MERIT_ACQUIRE,
    MERIT_FORTIFIED,
    MERIT_STRONGHOLD,
    BAND_EXPLOITED,
    BAND_FORTIFIED,
    BAND_STRONGHOLD,
    _decay_rate,
    compute_cp_decay,
    effective_undermining,
)

# ─── _decay_rate ─────────────────────────────────────────────────────────────


class TestDecayRate:
    """Tests for the internal _decay_rate helper."""

    # ── below-threshold: no decay regardless of state ────────────────────────

    def test_below_25_pct_no_decay_stronghold(self):
        assert _decay_rate("Stronghold", 0.0) == 0.0

    def test_below_25_pct_no_decay_fortified(self):
        assert _decay_rate("Fortified", 0.24) == 0.0

    def test_below_25_pct_no_decay_exploited(self):
        assert _decay_rate("Exploited", 0.25) == 0.0

    # ── unknown / non-decaying states ─────────────────────────────────────────

    def test_unoccupied_state_no_decay(self):
        assert _decay_rate("Unoccupied", 0.8) == 0.0

    def test_contested_state_no_decay(self):
        assert _decay_rate("Contested", 1.0) == 0.0

    def test_none_state_no_decay(self):
        assert _decay_rate(None, 0.9) == 0.0

    # ── Stronghold min endpoint (25.1%) ──────────────────────────────────────

    def test_stronghold_at_min_progress(self):
        # At 25.1% → 2.6%
        rate = _decay_rate("Stronghold", 0.251)
        assert rate == pytest.approx(0.026, abs=1e-6)

    # ── Stronghold max endpoint (100%) ──────────────────────────────────────

    def test_stronghold_at_100_pct(self):
        # At 100% → 15.6%
        rate = _decay_rate("Stronghold", 1.0)
        assert rate == pytest.approx(0.156, abs=1e-6)

    # ── Stronghold midpoint (linear interpolation check) ─────────────────────

    def test_stronghold_midpoint(self):
        # Midpoint between 0.251 and 1.0 → midpoint rate between 0.026 and 0.156
        mid_prog = (0.251 + 1.0) / 2
        expected_rate = (0.026 + 0.156) / 2
        rate = _decay_rate("Stronghold", mid_prog)
        assert rate == pytest.approx(expected_rate, abs=1e-6)

    # ── Fortified min endpoint ────────────────────────────────────────────────

    def test_fortified_at_min_progress(self):
        # At 25.1% → 0.1%
        rate = _decay_rate("Fortified", 0.251)
        assert rate == pytest.approx(0.001, abs=1e-6)

    # ── Exploited min endpoint ────────────────────────────────────────────────

    def test_exploited_at_min_progress(self):
        # At 25.1% → 0.1%
        rate = _decay_rate("Exploited", 0.251)
        assert rate == pytest.approx(0.001, abs=1e-6)

    # ── Progress clamped to [min_prog, max_prog] ──────────────────────────────

    def test_stronghold_progress_above_1_clamped_to_max(self):
        rate_at_100 = _decay_rate("Stronghold", 1.0)
        rate_above = _decay_rate("Stronghold", 1.5)
        assert rate_at_100 == pytest.approx(rate_above, abs=1e-9)


# ─── compute_cp_decay ────────────────────────────────────────────────────────


class TestComputeCpDecay:
    """Tests for the public compute_cp_decay function."""

    # ── non-decaying states return 0 ─────────────────────────────────────────

    def test_unoccupied_returns_0(self):
        assert compute_cp_decay("Unoccupied", 0.8, 10_000) == 0

    def test_contested_returns_0(self):
        assert compute_cp_decay("Contested", 0.9, 5_000) == 0

    def test_none_state_returns_0(self):
        assert compute_cp_decay(None, 0.7, 8_000) == 0

    # ── zero or missing undermining returns 0 ────────────────────────────────

    def test_zero_undermining_returns_0(self):
        assert compute_cp_decay("Stronghold", 1.0, 0) == 0

    def test_none_undermining_returns_0(self):
        assert compute_cp_decay("Stronghold", 1.0, None) == 0

    def test_negative_undermining_returns_0(self):
        # Negative U should be treated as <= 0
        assert compute_cp_decay("Stronghold", 1.0, -500) == 0

    # ── below 25% progress returns 0 decay ───────────────────────────────────

    def test_below_25_pct_stronghold_no_decay(self):
        assert compute_cp_decay("Stronghold", 0.1, 50_000) == 0

    # ── decay is capped at the undermining value ──────────────────────────────

    def test_decay_capped_at_undermining(self):
        # Very small undermining — decay must not exceed it
        small_u = 10
        decay = compute_cp_decay("Stronghold", 1.0, small_u)
        assert decay <= small_u

    # ── Stronghold at 100% progress ──────────────────────────────────────────

    def test_stronghold_100pct_large_undermining(self):
        """At 100% Stronghold, decay rate = 15.6%.
        CP = MERIT_STRONGHOLD + 1.0 × BAND_STRONGHOLD = 667_000 + 334_000 = 1_001_000
        raw_decay = 1_001_000 × 0.156 = 156_156
        With enough undermining, result should equal int(156_156).
        """
        cp = MERIT_STRONGHOLD + 1.0 * BAND_STRONGHOLD          # 1_001_000
        expected = int(cp * 0.156)                              # 156_156
        decay = compute_cp_decay("Stronghold", 1.0, 1_000_000)  # large U
        assert decay == expected

    # ── Exploited at 50% progress ─────────────────────────────────────────────

    def test_exploited_50pct_progress(self):
        """At 50% Exploited:
        decay_rate via linear interp between (0.251, 0.001) and (1.0, ~0.06195).
        CP = MERIT_ACQUIRE + 0.5 × BAND_EXPLOITED = 120_000 + 0.5 × 213_000 = 226_500.
        """
        progress = 0.5
        from services.decay import _DECAY_EXPLOITED
        min_prog, min_rate, max_prog, max_rate = _DECAY_EXPLOITED
        t = (progress - min_prog) / (max_prog - min_prog)
        expected_rate = min_rate + t * (max_rate - min_rate)
        cp = MERIT_ACQUIRE + progress * BAND_EXPLOITED
        expected_decay = int(cp * expected_rate)
        decay = compute_cp_decay("Exploited", progress, 1_000_000)
        assert decay == expected_decay

    # ── none / null control_progress treated as 0.0 ──────────────────────────

    def test_none_progress_treated_as_zero(self):
        # progress=None → 0.0 → below 0.251 → no decay
        assert compute_cp_decay("Stronghold", None, 50_000) == 0


# ─── effective_undermining ───────────────────────────────────────────────────


class TestEffectiveUndermining:
    """Tests for the effective_undermining helper."""

    def test_zero_decay_returns_undermining_unchanged(self):
        assert effective_undermining(5_000, 0) == 5_000

    def test_partial_decay_reduces_undermining(self):
        assert effective_undermining(5_000, 2_000) == 3_000

    def test_full_decay_equals_undermining_returns_0(self):
        assert effective_undermining(5_000, 5_000) == 0

    def test_decay_exceeds_undermining_floors_at_0(self):
        assert effective_undermining(5_000, 9_000) == 0

    def test_none_undermining_treated_as_0(self):
        assert effective_undermining(None, 1_000) == 0

    def test_none_decay_treated_as_0(self):
        assert effective_undermining(3_000, None) == 3_000

    def test_both_none_returns_0(self):
        assert effective_undermining(None, None) == 0

    def test_zero_undermining_returns_0(self):
        assert effective_undermining(0, 0) == 0
