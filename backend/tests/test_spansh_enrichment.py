"""Unit tests for the platinum/boom/pristine detection in routers/spansh.py.

Platinum: only Metallic rings count (laser-minable Platinum).  A 2026-09-09
change had flipped this to Metal Rich; players reported it as counting
non-metallic hotspots, and it was reverted on 2026-10-10.

Boom: counted per station, through the station's controlling faction's
active_states -- see _count_boom_stations.
"""

from routers.spansh import (
    _check_bodies_for_platinum,
    _check_body_for_platinum,
    _check_system_for_pristine,
    _count_boom_stations,
)

# Borann A 2 (trimmed from Spansh bodies/search): its Metal Rich ring has a
# Platinum hotspot, which must NOT count; the Icy ring is noise.
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


def test_platinum_on_metallic_ring_counts():
    body = {"rings": [{"type": "Metallic", "signals": [{"name": "Platinum"}]}]}
    assert _check_body_for_platinum(body) is True


def test_platinum_on_metal_rich_ring_is_rejected():
    assert _check_body_for_platinum(BORANN_A2) is False
    assert _check_bodies_for_platinum([BORANN_A2]) is False


def test_bodies_list_finds_metallic_platinum_among_others():
    metallic = {"rings": [{"type": "Metallic", "signals": [{"name": "Platinum"}]}]}
    assert _check_bodies_for_platinum([BORANN_A2, metallic]) is True


def test_platinum_on_icy_or_rocky_ring_is_rejected():
    body = {"rings": [{"type": "Icy", "signals": [{"name": "Platinum"}]},
                      {"type": "Rocky", "signals": [{"name": "Platinum"}]}]}
    assert _check_body_for_platinum(body) is False


def test_metallic_ring_without_platinum_signal_is_false():
    body = {"rings": [{"type": "Metallic", "signals": [{"name": "Painite"}]}]}
    assert _check_body_for_platinum(body) is False


def test_no_rings_is_false():
    assert _check_body_for_platinum({"name": "empty body"}) is False


def test_malformed_body_does_not_raise():
    assert _check_body_for_platinum({}) is False
    assert _check_bodies_for_platinum([None, {}, "not a dict"]) is False


# Trimmed from the live Spansh system record for Muang, 2026-10-10.
# The Winged Hussars' station-level state reads "Boom" here, but the
# faction also has Civil Liberty active -- the per-faction active_states
# list is what has to be checked.
MUANG = {
    "minor_faction_presences": [
        {"name": "Amsitia Holdings", "state": "Boom", "active_states": ["Boom"]},
        {"name": "Muang Gold Posse", "state": "None", "active_states": None},
        {"name": "The Winged Hussars", "state": "Boom", "active_states": ["Boom", "Civil Liberty"]},
    ],
    "stations": [
        {"name": "Al-Khujandi Enterprise", "controlling_minor_faction": "The Winged Hussars",
         "controlling_minor_faction_state": "Boom", "has_market": True},
        {"name": "Morgan Terminal", "controlling_minor_faction": "Amsitia Holdings",
         "controlling_minor_faction_state": "Boom", "has_market": None},
        {"name": "Hyakutake Settlement", "controlling_minor_faction": "Amsitia Holdings",
         "controlling_minor_faction_state": "Boom", "has_market": True},
        {"name": "KFX-L2J", "controlling_minor_faction": "FleetCarrier", "has_market": True},
    ],
}


def test_boom_counts_market_stations_of_booming_factions():
    # Morgan Terminal has no market; the fleet carrier isn't a faction
    assert _count_boom_stations(MUANG) == 2


def test_boom_uses_faction_active_states_not_station_state():
    # Station-level state shows the faction's other state; Boom is still active
    system = {
        "minor_faction_presences": [
            {"name": "A", "state": "Civil Liberty", "active_states": ["Civil Liberty", "Boom"]},
        ],
        "stations": [
            {"name": "S", "controlling_minor_faction": "A",
             "controlling_minor_faction_state": "Civil Liberty", "has_market": True},
        ],
    }
    assert _count_boom_stations(system) == 1


def test_booming_faction_without_stations_does_not_count():
    # The old check flagged any booming faction in the system
    system = {
        "minor_faction_presences": [
            {"name": "Booming", "active_states": ["Boom"]},
            {"name": "Owner", "active_states": ["War"]},
        ],
        "stations": [{"name": "S", "controlling_minor_faction": "Owner", "has_market": True}],
    }
    assert _count_boom_stations(system) == 0


def test_boom_active_state_as_dict():
    system = {
        "minor_faction_presences": [{"name": "A", "active_states": [{"name": "Boom"}]}],
        "stations": [{"name": "S", "controlling_minor_faction": "A", "has_market": True}],
    }
    assert _count_boom_stations(system) == 1


def test_boom_malformed_system_does_not_raise():
    assert _count_boom_stations({}) == 0
    assert _count_boom_stations({"minor_faction_presences": [None], "stations": ["x"]}) == 0


def test_pristine_reserve_top_level():
    assert _check_system_for_pristine({"reserve_level": "Pristine"}) is True


def test_pristine_reserve_per_body():
    system = {"bodies": [{"reserve_level": "Major"}, {"reserve_level": "Pristine"}]}
    assert _check_system_for_pristine(system) is True


def test_no_pristine_reserve_is_false():
    system = {"bodies": [{"reserve_level": "Common"}, {"reserve_level": "Low"}]}
    assert _check_system_for_pristine(system) is False
