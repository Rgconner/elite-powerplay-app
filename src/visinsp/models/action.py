"""Action model — what to do when an inspection passes or fails."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Union


@dataclass
class GpioAction:
    """Drive an output pin HIGH, LOW, or pulse for N ms."""

    type: str = "gpio"
    pin_id: str = ""
    mode: str = "HIGH"  # HIGH | LOW | PULSE
    duration_ms: int = 500  # used when mode == PULSE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "gpio",
            "pin_id": self.pin_id,
            "mode": self.mode,
            "duration_ms": int(self.duration_ms),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GpioAction":
        return cls(
            pin_id=str(data.get("pin_id", "")),
            mode=str(data.get("mode", "HIGH")).upper(),
            duration_ms=int(data.get("duration_ms", 500)),
        )


@dataclass
class SoundAction:
    """Play a beep on the host machine."""

    type: str = "sound"
    wav: str = ""  # optional path; empty = use default beep
    frequency_hz: int = 1000
    duration_ms: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "sound",
            "wav": self.wav,
            "frequency_hz": int(self.frequency_hz),
            "duration_ms": int(self.duration_ms),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SoundAction":
        return cls(
            wav=str(data.get("wav", "")),
            frequency_hz=int(data.get("frequency_hz", 1000)),
            duration_ms=int(data.get("duration_ms", 300)),
        )


@dataclass
class VisualAction:
    """Push a 'flash' event over WebSocket so the UI shows a visual alert."""

    type: str = "visual"
    color: str = "red"  # red | yellow | green | blue
    duration_ms: int = 1500
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "visual",
            "color": self.color,
            "duration_ms": int(self.duration_ms),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualAction":
        return cls(
            color=str(data.get("color", "red")),
            duration_ms=int(data.get("duration_ms", 1500)),
            message=str(data.get("message", "")),
        )


@dataclass
class NotificationAction:
    """Show an in-app notification (toast / inline notification)."""

    type: str = "notification"
    title: str = "Inspection Alert"
    body: str = ""
    kind: str = "error"  # error | warning | info | success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "notification",
            "title": self.title,
            "body": self.body,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationAction":
        return cls(
            title=str(data.get("title", "Inspection Alert")),
            body=str(data.get("body", "")),
            kind=str(data.get("kind", "error")),
        )


# Union of all action types
Action = Union[GpioAction, SoundAction, VisualAction, NotificationAction]


def action_from_dict(data: Dict[str, Any]) -> Action:
    """Build the right Action subclass from a dict based on its 'type' field."""
    t = str(data.get("type", "")).lower()
    if t == "gpio":
        return GpioAction.from_dict(data)
    if t == "sound":
        return SoundAction.from_dict(data)
    if t == "visual":
        return VisualAction.from_dict(data)
    if t == "notification":
        return NotificationAction.from_dict(data)
    raise ValueError(f"Unknown action type: {t!r}")


def actions_to_dicts(actions: List[Action]) -> List[Dict[str, Any]]:
    return [a.to_dict() for a in actions]


def actions_from_dicts(items: List[Dict[str, Any]]) -> List[Action]:
    return [action_from_dict(d) for d in (items or [])]


def new_action_id() -> str:
    return f"act_{uuid.uuid4().hex[:8]}"


__all__ = [
    "Action",
    "GpioAction",
    "SoundAction",
    "VisualAction",
    "NotificationAction",
    "action_from_dict",
    "actions_to_dicts",
    "actions_from_dicts",
    "new_action_id",
]
