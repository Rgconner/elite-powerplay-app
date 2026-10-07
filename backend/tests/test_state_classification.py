"""Unit tests for backend/services/state_classification.py.

Owned-state and Contested cases are golden data pulled directly from the
live pp_system_snapshots table (2026-09-09) — real examples, not invented.
Unoccupied/Expansion cases are synthetic, clearly marked: no real Expansion
row exists in the DB yet (see state_classification.py's module docstring —
ingestion never stores solo-power Unoccupied systems), so these assert the
classifier's intended behavior once that data exists, not a verified read.
"""

from services.state_classification import SystemState, classify_system

# ─── Golden data: real rows from the live DB, 2026-09-09 ──────────────────────


def test_stronghold_real_row():
    # Synteini, owner Zemina Torval
    result = classify_system("Stronghold", "A. Lavigny-Duval,Denton Patreus,Yuri Grom,Zemina Torval")
    assert result.state == SystemState.STRONGHOLD


def test_fortified_real_row():
    # G 268-47, owner Zemina Torval
    result = classify_system(
        "Fortified",
        "Aisling Duval,Archon Delaine,Denton Patreus,Li Yong-Rui,Pranav Antal,Yuri Grom,Zemina Torval,Jerome Archer",
    )
    assert result.state == SystemState.FORTIFIED


def test_exploited_real_row():
    # Col 285 Sector NE-R a34-2, owner Zemina Torval
    result = classify_system(
        "Exploited",
        "A. Lavigny-Duval,Aisling Duval,Denton Patreus,Li Yong-Rui,Yuri Grom,Zemina Torval,Jerome Archer",
    )
    assert result.state == SystemState.EXPLOITED


def test_contested_real_row():
    # Sumarr, no controlling power, 5 powers with conflict_progress entries
    result = classify_system("Contested", "Edmund Mahon,Felicia Winters,Li Yong-Rui,Zemina Torval,Jerome Archer")
    assert result.state == SystemState.CONTESTED
    assert "5 powers" in result.reasons[0]


# ─── Synthetic: no real Expansion/Unoccupied row exists yet ──────────────────


def test_unoccupied_no_presence():
    result = classify_system("Unoccupied", None)
    assert result.state == SystemState.UNOCCUPIED


def test_unoccupied_empty_powers_list():
    result = classify_system("Unoccupied", "")
    assert result.state == SystemState.UNOCCUPIED


def test_expansion_solo_push():
    result = classify_system("Unoccupied", "Zemina Torval")
    assert result.state == SystemState.EXPANSION
    assert "solo expansion" in result.reasons[0]


def test_unoccupied_with_two_powers_is_contested_not_expansion():
    # Defensive: if ingestion ever stores a raw 'Unoccupied' row (not yet
    # collapsed to 'Contested') with 2+ powers, it must still classify as
    # Contested — the label should never depend on which ingestion pass
    # wrote the row.
    result = classify_system("Unoccupied", "Zemina Torval,Yuri Grom")
    assert result.state == SystemState.CONTESTED


# ─── Edge cases ────────────────────────────────────────────────────────────


def test_owned_state_ignores_powers_list_noise():
    # Real data shows owned rows can carry a long powers_list (other powers
    # with incidental presence) — must not affect the owned classification.
    result = classify_system("Stronghold", "A,B,C,D,E,F,G,H")
    assert result.state == SystemState.STRONGHOLD


def test_none_power_state_falls_back_to_unoccupied_path():
    result = classify_system(None, None)
    assert result.state == SystemState.UNOCCUPIED


def test_powers_present_count_strips_whitespace_and_empties():
    from services.state_classification import powers_present_count

    assert powers_present_count(None) == 0
    assert powers_present_count("") == 0
    assert powers_present_count("A") == 1
    assert powers_present_count("A,B,C") == 3
