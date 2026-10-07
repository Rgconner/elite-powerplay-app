"""Unit tests for the platinum/boom/pristine detection in routers/spansh.py.

No test coverage existed for this before 2026-09-09 -- that's exactly how
the ring-type bug (Metallic vs. Metal Rich, see _check_body_for_platinum's
docstring) went unnoticed. Golden case below is real data pulled live from
Spansh's bodies/search API for Borann, a well-known real Platinum mining
system, confirming the fix against the actual game data it's meant to
model, not just internally-consistent logic.
"""

from routers.spansh import (
    _check_bodies_for_platinum,
    _check_body_for_platinum,
    _check_system_for_boom,
    _check_system_for_pristine,
)

# Trimmed from a live Spansh bodies/search response for "Borann", 2026-09-09.
# Borann A 2's Metal Rich ring is the real, well-known Platinum source here;
# its Icy ring (no platinum) is included to prove the ring-type filter still
# excludes non-matching rings on the SAME body, not just different bodies.
BORANN_A2 = {
    "name": "Borann A 2",
    "rings": [
        {
            "type": "Metal Rich",
            "signals": [
                {"name": "Monazite"}, {"name": "Painite"}, {"name": "Platinum"},
                {"name": "Rhodplumsite"}, {"name": "Serendibite"},
            ],
        },
        {
            "type": "Icy",
            "signals": [
                {"name": "Alexandrite"}, {"name": "Bromellite"}, {"name": "Grandidierite"},
                {"name": "Low Temperature Diamonds"}, {"name": "Void Opal"}, {"name": "Tritium"},
            ],
        },
    ],
}


def test_borann_real_data_detects_platinum_on_metal_rich_ring():
    assert _check_body_for_platinum(BORANN_A2) is True


def test_bodies_list_wrapper_finds_it_too():
    assert _check_bodies_for_platinum([BORANN_A2]) is True


def test_platinum_on_metallic_ring_is_rejected():
    # The bug this replaces: Metallic rings run Palladium/Gold-type
    # materials in real ED mechanics, not Platinum. A body whose ONLY
    # platinum signal sits on a Metallic ring should NOT count.
    body = {"rings": [{"type": "Metallic", "signals": [{"name": "Platinum"}]}]}
    assert _check_body_for_platinum(body) is False


def test_platinum_on_icy_or_rocky_ring_is_rejected():
    body = {"rings": [{"type": "Icy", "signals": [{"name": "Platinum"}]}]}
    assert _check_body_for_platinum(body) is False


def test_metal_rich_ring_without_platinum_signal_is_false():
    body = {"rings": [{"type": "Metal Rich", "signals": [{"name": "Painite"}]}]}
    assert _check_body_for_platinum(body) is False


def test_no_rings_is_false():
    assert _check_body_for_platinum({"name": "empty body"}) is False


def test_malformed_body_does_not_raise():
    assert _check_body_for_platinum({}) is False
    assert _check_bodies_for_platinum([None, {}, "not a dict"]) is False


def test_boom_active_state_as_plain_string():
    system = {"minor_faction_presences": [{"active_states": ["Boom"]}]}
    assert _check_system_for_boom(system) is True


def test_boom_active_state_as_dict():
    system = {"minor_faction_presences": [{"active_states": [{"name": "Boom"}]}]}
    assert _check_system_for_boom(system) is True


def test_no_boom_state_is_false():
    system = {"minor_faction_presences": [{"active_states": ["Expansion", "War"]}]}
    assert _check_system_for_boom(system) is False


def test_pristine_reserve_top_level():
    assert _check_system_for_pristine({"reserve_level": "Pristine"}) is True


def test_pristine_reserve_per_body():
    system = {"bodies": [{"reserve_level": "Major"}, {"reserve_level": "Pristine"}]}
    assert _check_system_for_pristine(system) is True


def test_no_pristine_reserve_is_false():
    system = {"bodies": [{"reserve_level": "Common"}, {"reserve_level": "Low"}]}
    assert _check_system_for_pristine(system) is False
