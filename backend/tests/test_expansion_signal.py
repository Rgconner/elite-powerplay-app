"""Unit tests for compute_expansion_signal in services/state_classification.py.

Golden data: Sumarr's real conflict_progress from the live DB (2026-09-09) —
[{"power": "Edmund Mahon", "progress": 0.289208}, {"power": "Felicia Winters",
"progress": 0.133833}, {"power": "Li Yong-Rui", "progress": 0.005958},
{"power": "Zemina Torval", "progress": 0.0}, {"power": "Jerome Archer",
"progress": 0.014442}].
"""

import json

from services.state_classification import compute_expansion_signal

SUMARR_CONFLICT_PROGRESS = json.dumps([
    {"power": "Edmund Mahon", "progress": 0.289208},
    {"power": "Felicia Winters", "progress": 0.133833},
    {"power": "Li Yong-Rui", "progress": 0.005958},
    {"power": "Zemina Torval", "progress": 0.0},
    {"power": "Jerome Archer", "progress": 0.014442},
])


def test_sumarr_zemina_is_far_behind_but_within_snipe_threshold():
    # Zemina at 0.0 vs leader Edmund Mahon at 0.289208 -- gap is 0.289, under
    # the default 0.5 threshold, so still technically snipable by the numbers
    # (this module makes no claim about whether it's actually worth doing).
    result = compute_expansion_signal("Zemina Torval", SUMARR_CONFLICT_PROGRESS)
    assert result.leading_rival == "Edmund Mahon"
    assert result.leading_rival_progress == 0.289208
    assert result.our_progress == 0.0
    assert round(result.gap_to_lead, 6) == -0.289208
    assert result.snipable is True


def test_sumarr_edmund_mahon_is_leading_not_snipable():
    result = compute_expansion_signal("Edmund Mahon", SUMARR_CONFLICT_PROGRESS)
    assert result.gap_to_lead > 0
    assert result.snipable is False


def test_gap_beyond_threshold_is_not_snipable():
    data = json.dumps([{"power": "Us", "progress": 0.0}, {"power": "Rival", "progress": 0.9}])
    result = compute_expansion_signal("Us", data, snipe_gap_threshold=0.5)
    assert result.snipable is False


def test_no_rivals_present():
    data = json.dumps([{"power": "Us", "progress": 0.2}])
    result = compute_expansion_signal("Us", data)
    assert result.leading_rival is None
    assert result.snipable is False


def test_null_conflict_progress_returns_none():
    assert compute_expansion_signal("Us", None) is None


def test_empty_conflict_progress_returns_none():
    assert compute_expansion_signal("Us", "[]") is None


def test_malformed_json_returns_none():
    assert compute_expansion_signal("Us", "{not valid json") is None


def test_percentage_can_exceed_one_hundred_percent():
    # Confirmed via inara.cz/elite/power-contested/4/: this is a horse race,
    # not a 0-1 safe-zone position -- rivals can exceed 1.0 (100%).
    data = json.dumps([{"power": "Us", "progress": 1.138}, {"power": "Rival", "progress": 2.18}])
    result = compute_expansion_signal("Us", data)
    assert result.leading_rival_progress == 2.18
    assert result.snipable is False  # gap of -1.042 exceeds default 0.5 threshold


# ─── cz_incoming: the real 30,000-control-point conflict threshold ─────────
# Confirmed 2026-09-09: NOT the 120,000-merit acquisition threshold (that
# decides who wins at cycle end) -- CZs start once 2+ powers cross 30,000
# (normalized: 30,000/120,000 = 0.25).

TRIANGULI_CONFLICT_PROGRESS = json.dumps([
    {"power": "Aisling Duval", "progress": 1.024983},
    {"power": "Li Yong-Rui", "progress": 1.433217},
])


def test_trianguli_real_data_both_powers_past_conflict_threshold():
    # Real pp_system_snapshots data for Trianguli Sector GW-V a2-2 -- both
    # powers are well past 0.25, so CZs are guaranteed there right now.
    result = compute_expansion_signal("Aisling Duval", TRIANGULI_CONFLICT_PROGRESS)
    assert result.cz_incoming is True


def test_sumarr_real_data_only_one_power_past_threshold_no_cz():
    # Real Sumarr data: Edmund Mahon (0.289208) is past 0.25, but everyone
    # else (incl. Felicia Winters at 0.133833) is below it -- only one
    # power qualifies, so no conflict is guaranteed yet.
    result = compute_expansion_signal("Zemina Torval", SUMARR_CONFLICT_PROGRESS)
    assert result.cz_incoming is False


def test_cz_incoming_true_when_exactly_two_powers_at_threshold():
    data = json.dumps([{"power": "Us", "progress": 0.25}, {"power": "Rival", "progress": 0.25}])
    result = compute_expansion_signal("Us", data)
    assert result.cz_incoming is True


def test_cz_incoming_false_when_only_one_power_past_threshold():
    data = json.dumps([{"power": "Us", "progress": 0.25}, {"power": "Rival", "progress": 0.24}])
    result = compute_expansion_signal("Us", data)
    assert result.cz_incoming is False


def test_cz_incoming_false_with_no_rivals():
    data = json.dumps([{"power": "Us", "progress": 1.0}])
    result = compute_expansion_signal("Us", data)
    assert result.cz_incoming is False
