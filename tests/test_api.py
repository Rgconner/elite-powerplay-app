"""Smoke tests for the Flask app + routes."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the active config at a fresh config in tmp_path
    cfg = tmp_path / "config.json"
    cfg.write_text('''{
      "app": {"name":"Visual Inspector","version":"0.0.0","environment":"wsl",
              "host":"127.0.0.1","port":0,"secret_key":"x","theme":"g100"},
      "paths": {"data_dir":"_data","references_dir":"_data/references",
                "captures_dir":"_data/captures","alerts_dir":"_data/alerts",
                "db_path":"_data/v.db","mock_pins_path":"_data/pins.json",
                "sample_images_dir":"_data/samples","log_file":""},
      "environment": {"name":"wsl","force_backend":"mock"},
      "logging": {"level":"WARNING","log_to_file":false,"log_to_console":false,
                  "max_bytes":1000,"backup_count":1},
      "gpio": {"mode":"BCM","default_debounce_ms":200,"cleanup_on_exit":true},
      "camera": {"probe_max_index":2,"capture_timeout_s":5,"wsl_sample_fallback":true},
      "inspection": {"match_method":"TM_CCOEFF_NORMED","secondary_metric":"none",
                     "save_captures":false,"save_passed_captures":false,"max_image_dimension":1280},
      "threshold": {"default":0.85,"default_step":0.005,"min":0.5,"max":0.99,"history_retention_days":90},
      "alerts": {"retention_days":30,"auto_dismiss_after_hours":0},
      "pins": [
        {"id":"trig1","name":"T1","bcm":17,"direction":"input","pull":"up",
         "active_low":true,"debounce_ms":200,"edge":"falling","enabled":true},
        {"id":"alert1","name":"Alert","bcm":27,"direction":"output","pull":null,
         "active_low":false,"debounce_ms":0,"edge":"none","enabled":true}
      ],
      "cameras": [{"id":"cam_0","name":"Camera 0","device_index":0}]
    }''')
    monkeypatch.setenv("VISINSP_CONFIG", str(cfg))
    monkeypatch.chdir(tmp_path)

    # Reset the global modules so they pick up the new config
    from visinsp.actions import reset_action_registry
    from visinsp.core.event_bus import reset_event_bus
    reset_action_registry()
    reset_event_bus()

    from visinsp.api import create_app
    app, socketio, ctx = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, ctx


def test_healthz(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200


def test_dashboard_renders(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert b"Visual" in r.data


def test_list_pins(client):
    c, _ = client
    r = c.get("/api/pins")
    assert r.status_code == 200
    data = r.get_json()
    assert any(p["id"] == "trig1" for p in data["pins"])


def test_toggle_pin_in_mock_mode(client):
    c, ctx = client
    # Mock backend supports toggle
    r = c.post("/api/pins/trig1/toggle")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "level" in body


def test_create_and_list_job(client):
    c, ctx = client
    # Need a reference first
    c.post("/api/references", json={
        "name": "Ref1", "camera_id": "cam_0",
        "image_b64": "",  # invalid -> 400, just exercise the route
    })
    r = c.get("/api/jobs")
    assert r.status_code == 200


def test_settings_get_put(client):
    c, _ = client
    r = c.get("/api/settings")
    assert r.status_code == 200
    s = r.get_json()["settings"]
    assert s["default_threshold"] == 0.85
    r = c.put("/api/settings", json={"default_threshold": 0.9})
    assert r.status_code == 200
    assert r.get_json()["settings"]["default_threshold"] == 0.9
   