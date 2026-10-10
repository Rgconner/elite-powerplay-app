"""Contested vs expansion: every Unoccupied system lands in exactly one list
per power (scoring.classify_acquisition)."""

import json

import pytest

from services.scoring import DEFAULTS, classify_acquisition, contested_min_progress, fraction_setting

ALD = "A. Lavigny-Duval"


def cp(**progress: float) -> str:
    names = {"ald": ALD, "lyr": "Li Yong-Rui", "aisling": "Aisling Duval", "grom": "Yuri Grom"}
    return json.dumps([{"power": names[k], "progress": v} for k, v in progress.items()])


@pytest.mark.parametrize("progress, expected", [
    # Puppis Sector ZJ-R a4-0: both far past the line -> contested only
    (cp(ald=2.730142, lyr=2.2644), "contested"),
    # rival past the old 25% conflict line but under 50%: an expansion target
    (cp(ald=0.335, aisling=0.269), "expansion"),
    # we're under 50% while the rival is well past it: not a race we're in yet
    (cp(ald=0.286, aisling=0.892), "expansion"),
    # solo push
    (cp(ald=0.40), "expansion"),
    # exactly on the line counts
    (cp(ald=0.50, grom=0.50), "contested"),
    # we're absent / at zero: neither list
    (cp(lyr=0.9, grom=0.6), None),
    (cp(ald=0.0, lyr=0.9), None),
])
def test_classification_at_default_threshold(progress, expected):
    assert classify_acquisition(ALD, progress, 0.50) == expected


def test_threshold_moves_systems_between_lists():
    progress = cp(ald=0.335, aisling=0.269)
    assert classify_acquisition(ALD, progress, 0.25) == "contested"
    assert classify_acquisition(ALD, progress, 0.50) == "expansion"


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]"])
def test_bad_conflict_progress_is_neither(raw):
    assert classify_acquisition(ALD, raw, 0.5) is None


def test_default_threshold_is_fifty_percent():
    assert contested_min_progress({}) == 0.50


@pytest.mark.parametrize("stored, expected", [(0.5, 0.5), (50.0, 0.5), (10.0, 0.10), (0.25, 0.25), (1.0, 1.0)])
def test_fraction_setting_accepts_admin_percents(stored, expected):
    # The Admin page's percent sliders save whole percents
    assert fraction_setting({"contested_min_progress": stored}, "contested_min_progress") == pytest.approx(expected)


def test_target_progress_defaults_are_fractions():
    for key in ("target_progress_critical", "target_progress_high", "target_progress_medium"):
        assert fraction_setting({}, key) == DEFAULTS[key] <= 1.0
