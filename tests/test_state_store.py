"""Tests for the SQLite state store."""

import os
import tempfile
from pathlib import Path

import pytest

from visinsp.core import StateStore
from visinsp.models import (
    AlertRecord,
    AlertVerdict,
    BoundingBox,
    GpioAction,
    InspectionResult,
    Job,
    NotificationAction,
    Pin,
    ReferenceImage,
    Settings,
    Trigger,
)


@pytest.fixture
def store():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    s = StateStore(Path(tmp.name))
    yield s
    s.close()
    os.unlink(tmp.name)


def test_schema_version_recorded(store):
    assert store.list_pins() == []


def test_pin_crud(store):
    pin = Pin(id="p1", bcm=17, name="Trigger 1", debounce_ms=200)
    store.upsert_pin(pin)
    got = store.get_pin("p1")
    assert got is not None
    assert got.bcm == 17
    assert got.name == "Trigger 1"
    store.delete_pin("p1")
    assert store.get_pin("p1") is None


def test_trigger_crud(store):
    store.upsert_pin(Pin(id="p1", bcm=17, name="Pin"))
    t = Trigger(id="t1", pin_id="p1", job_id="j1")
    store.upsert_trigger(t)
    assert store.get_trigger("t1").pin_id == "p1"
    assert len(store.list_triggers_for_pin("p1")) == 1
    store.delete_trigger("t1")
    assert store.get_trigger("t1") is None


def test_reference_with_bboxes(store):
    ref = ReferenceImage(
        id="r1", name="Good", camera_id="cam_0", image_path="/tmp/x.png",
        bboxes=[
            BoundingBox(id="b1", x=10, y=10, w=100, h=100, label="part"),
            BoundingBox(id="b2", x=200, y=50, w=80, h=80, weight=2.0),
        ],
    )
    store.upsert_reference(ref)
    got = store.get_reference("r1")
    assert got is not None
    assert len(got.bboxes) == 2
    assert got.bboxes[1].weight == 2.0
    # Updating replaces all bboxes
    ref.bboxes = ref.bboxes[:1]
    store.upsert_reference(ref)
    got = store.get_reference("r1")
    assert len(got.bboxes) == 1


def test_job_crud(store):
    store.upsert_reference(ReferenceImage(id="r1", name="x", camera_id="c", image_path="/x"))
    j = Job(
        id="j1", name="Test job", reference_id="r1", camera_id="cam_0",
        threshold=0.9, actions_on_fail=[GpioAction(pin_id="alert", mode="HIGH")],
    )
    store.upsert_job(j)
    got = store.get_job("j1")
    assert got is not None
    assert got.threshold == 0.9
    assert len(got.actions_on_fail) == 1
    assert isinstance(got.actions_on_fail[0], GpioAction)


def test_inspection_round_trip(store):
    store.upsert_job(Job(id="j1", name="J", reference_id="r1", camera_id="cam_0"))
    r = InspectionResult(
        id="i1", job_id="j1", trigger_id=None, captured_at="2024-01-01T00:00:00",
        score_overall=0.83, threshold=0.85, passed=False, image_path="/tmp/cap.jpg",
    )
    store.record_inspection(r)
    rows = store.list_inspections()
    assert len(rows) == 1
    assert rows[0].score_overall == 0.83
    assert rows[0].passed is False


def test_alert_crud(store):
    store.upsert_job(Job(id="j1", name="J", reference_id="r1", camera_id="cam_0"))
    store.record_inspection(InspectionResult(
        id="i1", job_id="j1", trigger_id=None, captured_at="x",
        score_overall=0.6, threshold=0.85, passed=False,
    ))
    a = AlertRecord(id="a1", inspection_id="i1", job_id="j1", raised_at="x", score=0.6, threshold=0.85)
    store.create_alert(a)
    store.dismiss_alert("a1", AlertVerdict.FALSE_POSITIVE, "x", notes="n")
    got = store.get_alert("a1")
    assert got.verdict == AlertVerdict.FALSE_POSITIVE
    assert got.dismissed_at == "x"


def test_settings_singleton(store):
    s1 = store.get_settings()
    s2 = store.get_settings()
    assert s1.id == "singleton"
    s1.theme = "white"
    store.save_settings(s1)
    assert store.get_settings().theme == "white"


def test_threshold_history(store):
    store.upsert_job(Job(id="j1", name="J", reference_id="r1", camera_id="cam_0"))
    store.record_threshold_change("j1", 0.85, 0.86, "false_positive", alert_id="a1", created_at="x")
    rows = store.list_threshold_history(job_id="j1")
    assert len(rows) == 1
    assert rows[0]["new_value"] == 0.86
