"""Tests for action registry + handler dispatch."""

import pytest

from visinsp.actions import (
    ActionRegistry,
    get_action_registry,
    reset_action_registry,
    set_gpio_backend,
    set_visual_emitter,
    set_socketio_emitter,
)
from visinsp.actions.gpio_action import GpioActionHandler
from visinsp.actions.visual_action import VisualActionHandler
from visinsp.actions.notification_action import NotificationActionHandler
from visinsp.models import (
    GpioAction,
    NotificationAction,
    VisualAction,
)


def test_default_registry_has_all_handlers():
    reset_action_registry()
    reg = get_action_registry()
    for t in ("gpio", "sound", "visual", "notification"):
        assert reg.has(t), f"missing handler for {t}"


def test_register_and_get():
    reg = ActionRegistry()
    def h(a, ctx): pass
    reg.register("custom", h)
    assert reg.get("custom") is h
    with pytest.raises(KeyError):
        reg.get("nope")


def test_gpio_action_with_no_backend_is_noop():
    set_gpio_backend(None)
    h = GpioActionHandler()
    h(GpioAction(pin_id="x", mode="HIGH"), {"alert_id": "a"})


def test_visual_action_with_emitter():
    captured = {}
    set_visual_emitter(lambda evt, data: captured.update(event=evt, data=data))
    h = VisualActionHandler()
    h(VisualAction(color="green", message="ok"), {"alert_id": "a"})
    assert captured["event"] == "visual_flash"
    assert captured["data"]["color"] == "green"


def test_notification_action_with_emitter():
    captured = {}
    set_socketio_emitter(lambda evt, data: captured.update(event=evt, data=data))
    h = NotificationActionHandler()
    h(NotificationAction(title="T", body="B", kind="warning"), {"alert_id": "a"})
    assert captured["event"] == "notification"
    assert captured["data"]["title"] == "T"
