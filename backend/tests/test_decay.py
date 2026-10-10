"""Unit tests for backend/services/decay.py.

Only pure calculation functions are imported — no database, no FastAPI.
Run with: pytest  (from the backend/ directory)

The golden cases are real journal observations (EDDN/Spansh, 2026-10-09)
of systems nobody was undermining, so their whole undermining value is
decay.
"""

import pytest
from services.decay import (
    BAND_FORTIFIED,
    compute_cp_decay,
    effective_undermining,
    start_of_cycle_progress,
)


# ─── Golden cases: real systems where undermining == decay ─────────────────


@pytest.mark.parametrize("state, progress, r, u", [
    # Stronghold at 100% at the tick: the maximum, 156,250
    ("Stronghold", 0.84383, 80, 156_250),
    ("Fortified", 0.587928, 6, 45_253),
    ("Exploited", 0.806368, 24_137, 15_508),
])
def test_real_unopposed_systems_decay_equals_undermining(state, progress, r, u):
    assert compute_cp_decay(state, progress, r, u) == u
    assert effective_undermining(u, compute_cp_decay(state, progress, r, u)) == 0


# ─── Shape ──────────────────────────────────────────────────────────────────
# Live progress already includes this cycle's R − U, so with R == U the
# live progress equals the progress at the tick.  U is large so the cap at
# U doesn't kick in.

BIG = 10**7


@pytest.mark.parametrize("state, max_decay", [
    ("Exploited", 21_875),
    ("Fortified", 83_281),
    ("Stronghold", 156_250),
])
def test_decay_at_100_percent(state, max_decay):
    assert compute_cp_decay(state, 1.0, BIG, BIG) == pytest.approx(max_decay, abs=1)


@pytest.mark.parametrize("state", ["Exploited", "Fortified", "Stronghold"])
def test_no_decay_at_or_below_25_percent(state):
    assert compute_cp_decay(state, 0.25, BIG, BIG) == 0
    assert compute_cp_decay(state, 0.10, BIG, BIG) == 0


def test_decay_is_linear_above_floor():
    half = compute_cp_decay("Stronghold", 0.625, BIG, BIG)   # halfway 25%→100%
    assert half == pytest.approx(156_250 / 2, abs=1)


def test_decay_uses_start_of_cycle_progress_not_live_progress():
    # A Fortified system at 30% at the tick, then reinforced to 60% live.
    # Decay is fixed at the tick, so it must match the 30% value.
    extra_r = int(0.30 * BAND_FORTIFIED)
    at_tick = compute_cp_decay("Fortified", 0.30, BIG, BIG)
    later = compute_cp_decay("Fortified", 0.60, BIG + extra_r, BIG)
    assert at_tick > 0
    assert later == at_tick


def test_start_of_cycle_progress_backs_out_r_and_u():
    p0 = start_of_cycle_progress("Stronghold", 0.84383, 80, 156_250)
    assert p0 == pytest.approx(1.0, abs=1e-6)


# ─── Edge cases ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ["Unoccupied", "Contested", None])
def test_non_decaying_states(state):
    assert compute_cp_decay(state, 0.9, 0, 50_000) == 0


@pytest.mark.parametrize("u", [0, None, -500])
def test_no_undermining_means_no_decay(u):
    assert compute_cp_decay("Stronghold", 1.0, 0, u) == 0


def test_capped_at_undermining():
    assert compute_cp_decay("Stronghold", 1.0, 0, 1_000) == 1_000


def test_missing_progress_returns_zero():
    assert compute_cp_decay("Stronghold", None, 0, 50_000) == 0


# ─── effective_undermining ─────────────────────────────────────────────────


def test_effective_undermining_subtracts_and_floors():
    assert effective_undermining(10_000, 4_000) == 6_000
    assert effective_undermining(1_000, 4_000) == 0
    assert effective_undermining(None, None) == 0
