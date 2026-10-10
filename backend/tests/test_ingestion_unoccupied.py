"""The Unoccupied (contested) pass is split per power to stay under Spansh's
10,000-result search cap, and must yield each multi-power system once."""

from services import ingestion


def test_unoccupied_pass_queries_each_power_and_dedupes(monkeypatch):
    shared = {"id64": 1, "power": ["A. Lavigny-Duval", "Li Yong-Rui"]}
    solo = {"id64": 2, "power": ["A. Lavigny-Duval"]}
    other = {"id64": 3, "power": ["Li Yong-Rui", "Zemina Torval"]}
    by_power = {
        "A. Lavigny-Duval": [shared, solo],
        "Li Yong-Rui": [shared, other],
        "Zemina Torval": [other],
    }
    queried = []

    def fake_fetch(power, page, metrics=None):
        queried.append((power, page))
        results = by_power.get(power, []) if page == 0 else []
        return {"count": len(results), "results": results}

    monkeypatch.setattr(ingestion, "_fetch_page_unoccupied", fake_fetch)
    monkeypatch.setattr(ingestion.time, "sleep", lambda s: None)

    ids = [s["id64"] for s in ingestion._iter_unoccupied_systems()]

    assert ids == [1, 3]                       # shared once, solo-power skipped
    assert {p for p, _ in queried} == set(ingestion.ALL_POWERS)


def test_unoccupied_pass_never_pages_past_the_cap(monkeypatch):
    pages = []

    def fake_fetch(power, page, metrics=None):
        pages.append(page)
        # Spansh reports the cap and would error past it
        return {"count": ingestion.SPANSH_MAX_RESULTS,
                "results": [{"id64": page * 1000 + i, "power": ["a", "b"]}
                            for i in range(ingestion.PAGE_SIZE)]}

    monkeypatch.setattr(ingestion, "ALL_POWERS", ["Only"])
    monkeypatch.setattr(ingestion, "_fetch_page_unoccupied", fake_fetch)
    monkeypatch.setattr(ingestion.time, "sleep", lambda s: None)

    list(ingestion._iter_unoccupied_systems())
    assert max(pages) == ingestion.SPANSH_MAX_RESULTS // ingestion.PAGE_SIZE - 1
