"""Runtime health monitoring (services/health_monitor.py)."""

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import health_monitor as hm


@pytest.fixture
def mon(monkeypatch):
    m = hm.HealthMonitor()
    monkeypatch.setattr(hm, "monitor", m)
    monkeypatch.setattr(hm, "ALERT_ES_URL", "")
    return m


class FakeRequest:
    def __init__(self, headers, peer="10.244.0.236"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("C", (), {"host": peer})()


@pytest.mark.parametrize("headers, expected", [
    ({"CF-Connecting-IP": "129.228.7.3", "X-Forwarded-For": "1.1.1.1, 10.0.0.1"}, "129.228.7.3"),
    ({"X-Forwarded-For": "129.228.7.3, 10.244.4.0"}, "129.228.7.3"),
    ({"X-Real-IP": "10.244.4.0"}, "10.244.4.0"),
    ({}, "10.244.0.236"),
])
def test_client_ip_prefers_the_real_browser_address(headers, expected):
    assert hm.client_ip(FakeRequest(headers)) == expected


def test_rate_limit_trips_after_limit_and_alerts_once(mon, monkeypatch):
    monkeypatch.setattr(hm, "CLIENT_RATE_LIMIT", 5)
    results = [mon.over_limit("129.228.7.3", "/api/spansh/enrich/batch") for _ in range(8)]
    assert results == [False] * 5 + [True] * 3
    assert mon.throttled == 3
    # Cooldown: three over-limit hits, one alert
    floods = [a for a in mon.recent_alerts if a["fingerprint"].startswith("ppa:client_flood")]
    assert len(floods) == 1
    assert floods[0]["src_ip"] == "129.228.7.3"
    assert floods[0]["tier"] == "immediate"


def test_rate_limit_is_per_client_and_endpoint(mon, monkeypatch):
    monkeypatch.setattr(hm, "CLIENT_RATE_LIMIT", 2)
    for _ in range(2):
        mon.over_limit("a", "/x")
    assert mon.over_limit("b", "/x") is False
    assert mon.over_limit("a", "/y") is False
    assert mon.over_limit("a", "/x") is True


def test_loop_stall_is_detected_and_names_in_flight_requests(mon, monkeypatch):
    monkeypatch.setattr(hm, "LOOP_TICK_S", 0.05)
    monkeypatch.setattr(hm, "LOOP_STALL_S", 0.1)

    async def scenario():
        mon.begin("/api/spansh/enrich/batch", "129.228.7.3")
        watcher = asyncio.create_task(mon.watch_loop())
        await asyncio.sleep(0.1)
        time.sleep(0.4)          # block the event loop, as the sync DB commit did
        await asyncio.sleep(0.1)
        watcher.cancel()

    asyncio.run(scenario())
    assert mon.stalls >= 1
    assert mon.max_loop_lag >= 0.3
    stall = next(a for a in mon.recent_alerts if a["fingerprint"] == "ppa:loop_stall")
    assert "/api/spansh/enrich/batch" in stall["message"]
    assert stall["raw"]["in_flight"] == {"/api/spansh/enrich/batch": 1}


def test_slow_endpoint_alert(mon, monkeypatch):
    monkeypatch.setattr(hm, "SLOW_P95_S", 1.0)
    for _ in range(hm.SLOW_MIN_SAMPLES):
        mon.end(mon.begin("/api/slow", "c"), 2.0)
    assert any(a["fingerprint"] == "ppa:slow_endpoint:/api/slow" for a in mon.recent_alerts)


def test_alert_document_has_anomaly_board_fields(mon):
    mon.alert("loop_stall", "immediate", "high risk", "msg", {"lag_s": 1.0})
    doc = mon.recent_alerts[0]
    for field in ("source_type", "source_id", "ts", "fingerprint", "urgency_label",
                  "urgency_score", "tier", "raw", "scored_at"):
        assert field in doc
    assert doc["source_type"] == "app_health"
    assert doc["tier"] in {"immediate", "investigate", "monitor"}


def test_middleware_throttles_with_429_and_exempts_health(mon, monkeypatch):
    monkeypatch.setattr(hm, "CLIENT_RATE_LIMIT", 3)
    app = FastAPI()
    app.add_middleware(hm.HealthMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/powers/{name}/systems")
    def systems(name: str):
        return []

    client = TestClient(app)
    headers = {"CF-Connecting-IP": "129.228.7.3"}
    codes = [client.get("/api/powers/X/systems", headers=headers).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert all(client.get("/health", headers=headers).status_code == 200 for _ in range(10))
    # Latency is recorded under the route template
    assert "/api/powers/{name}/systems" in mon.latencies
    assert not mon.in_flight
