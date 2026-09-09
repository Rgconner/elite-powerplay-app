"""Unit tests for backend/services/fortify_cause.py.

Golden data pulled from the live pp_system_snapshots table (2026-09-09).
"""

from services.fortify_cause import FortifyCause, classify_fortify_cause


def test_active_attack_real_row():
    # WISE 0855-0714, owner Jerome Archer: r=20363, u=87771, progress=-0.192
    result = classify_fortify_cause(control_progress=-0.192458486262694, reinforcement=20363, undermining=87771)
    assert result.cause == FortifyCause.ATTACK


def test_neglect_real_row():
    # Shorodo, owner Aisling Duval: r=0, u=0, progress=0.000569
    result = classify_fortify_cause(control_progress=0.000569, reinforcement=0, undermining=0)
    assert result.cause == FortifyCause.NEGLECT


def test_healthy_no_cause():
    result = classify_fortify_cause(control_progress=0.6, reinforcement=100, undermining=10)
    assert result.cause == FortifyCause.NONE


def test_attack_wins_even_at_high_progress():
    # Undermining exceeding reinforcement is ATTACK regardless of buffer size —
    # a rival actively pushing matters even before the buffer is critical.
    result = classify_fortify_cause(control_progress=0.8, reinforcement=100, undermining=500)
    assert result.cause == FortifyCause.ATTACK


def test_neglect_threshold_is_configurable():
    result = classify_fortify_cause(control_progress=0.3, reinforcement=0, undermining=0, neglect_threshold=0.5)
    assert result.cause == FortifyCause.NEGLECT


def test_tie_reinforcement_undermining_is_not_attack():
    # u > r is required for ATTACK; u == r falls through to the neglect check.
    result = classify_fortify_cause(control_progress=0.1, reinforcement=50, undermining=50)
    assert result.cause == FortifyCause.NEGLECT
