"""Spansh search paging: queries that reach Spansh's result cap are split by
X range so nothing is silently dropped, and every system is yielded once."""

import pytest

from services import ingestion


class FakeSpansh:
    """Mimics systems/search: filters on power/power_state/controlling_power
    and an inclusive x range, reports at most `cap` results, and fails on
    pages past the cap like the real API."""

    def __init__(self, systems, cap):
        self.systems = sorted(systems, key=lambda s: s["id64"])
        self.cap = cap
        self.calls = 0

    def __call__(self, payload, label, metrics=None):
        self.calls += 1
        f = payload["filters"]
        lo, hi = f["x"]["value"]
        matches = [
            s for s in self.systems
            if lo <= s["x"] <= hi
            and ("power" not in f or f["power"]["value"][0] in s["power"])
            and ("power_state" not in f or s["power_state"] == f["power_state"]["value"][0])
            and ("controlling_power" not in f or s.get("controlling_power") == f["controlling_power"]["value"][0])
        ]
        start = payload["page"] * payload["size"]
        if start >= self.cap:
            raise RuntimeError("Could not perform search")
        page = matches[:self.cap][start:start + payload["size"]]
        return {"count": min(len(matches), self.cap), "results": page}


@pytest.fixture(autouse=True)
def small_limits(monkeypatch):
    monkeypatch.setattr(ingestion, "SPANSH_MAX_RESULTS", 10)
    monkeypatch.setattr(ingestion, "PAGE_SIZE", 4)
    monkeypatch.setattr(ingestion.time, "sleep", lambda s: None)


def unoccupied(id64, x, powers):
    return {"id64": id64, "x": float(x), "power_state": "Unoccupied", "power": powers}


def test_query_over_the_cap_is_split_and_nothing_is_lost(monkeypatch):
    # 35 contested systems for one power: 3.5x the cap
    systems = [unoccupied(i, x=i * 7 - 120, powers=["Big", "Other"]) for i in range(35)]
    fake = FakeSpansh(systems, cap=10)
    monkeypatch.setattr(ingestion, "_post_search", fake)
    monkeypatch.setattr(ingestion, "ALL_POWERS", ["Big"])

    ids = [s["id64"] for s in ingestion._iter_unoccupied_systems()]

    assert sorted(ids) == list(range(35))      # all of them, no duplicates


def test_system_on_a_split_boundary_is_yielded_once(monkeypatch):
    # x=0 is the first split point; ranges are inclusive on both sides
    systems = [unoccupied(i, x=0, powers=["Big", "Other"]) for i in range(3)]
    systems += [unoccupied(100 + i, x=i + 1, powers=["Big", "Other"]) for i in range(12)]
    monkeypatch.setattr(ingestion, "_post_search", FakeSpansh(systems, cap=10))
    monkeypatch.setattr(ingestion, "ALL_POWERS", ["Big"])

    ids = [s["id64"] for s in ingestion._iter_unoccupied_systems()]

    assert len(ids) == len(set(ids)) == 15


def test_unoccupied_pass_queries_each_power_and_dedupes(monkeypatch):
    systems = [
        unoccupied(1, 5, ["A. Lavigny-Duval", "Li Yong-Rui"]),   # shared
        unoccupied(2, 6, ["A. Lavigny-Duval"]),                  # solo: skipped
        unoccupied(3, 7, ["Li Yong-Rui", "Zemina Torval"]),
    ]
    monkeypatch.setattr(ingestion, "_post_search", FakeSpansh(systems, cap=10))

    ids = [s["id64"] for s in ingestion._iter_unoccupied_systems()]

    assert ids == [1, 3]


def test_controlled_systems_are_split_too(monkeypatch):
    systems = [{"id64": i, "x": float(i), "controlling_power": "Big", "power": ["Big"],
                "power_state": "Fortified"} for i in range(25)]
    monkeypatch.setattr(ingestion, "_post_search", FakeSpansh(systems, cap=10))

    ids = [s["id64"] for s in ingestion._iter_power_systems("Big")]

    assert sorted(ids) == list(range(25))


def test_under_the_cap_needs_no_split(monkeypatch):
    systems = [unoccupied(i, i, ["Big", "Other"]) for i in range(9)]
    fake = FakeSpansh(systems, cap=10)
    monkeypatch.setattr(ingestion, "_post_search", fake)
    monkeypatch.setattr(ingestion, "ALL_POWERS", ["Big"])

    assert len(list(ingestion._iter_unoccupied_systems())) == 9
    assert fake.calls == 3                      # 9 results / 4 per page, no split
