"""GPIO pin configuration model."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class PinDirection(str, enum.Enum):
    INPUT = "input"
    OUTPUT = "output"


class PinEdge(str, enum.Enum):
    """Edge that fires a trigger. Only meaningful for input pins."""

    NONE = "none"
    RISING = "rising"
    FALLING = "falling"
    BOTH = "both"

    @classmethod
    def from_str(cls, v: Optional[str]) -> "PinEdge":
        if not v:
            return cls.NONE
        try:
            return cls(v.lower())
        except ValueError:
            return cls.NONE


@dataclass
class Pin:
    """A single BCM-numbered GPIO pin."""

    id: str
    bcm: int
    name: str
    direction: PinDirection = PinDirection.INPUT
    pull: Optional[str] = None  # "up", "down", or None
    active_low: bool = True
    debounce_ms: int = 200
    edge: PinEdge = PinEdge.NONE
    enabled: bool = True

    # Runtime state — never serialised into the config.
    current_level: Optional[int] = field(default=None, repr=False, compare=False)
    last_edge_at: Optional[float] = field(default=None, repr=False, compare=False)

    # ---- serialisation ----

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "bcm": self.bcm,
            "name": self.name,
            "direction": self.direction.value,
            "pull": self.pull,
            "active_low": self.active_low,
            "debounce_ms": self.debounce_ms,
            "edge": self.edge.value,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pin":
        return cls(
            id=str(data.get("id") or f"pin_{uuid.uuid4().hex[:8]}"),
            bcm=int(data["bcm"]),
            name=str(data.get("name") or f"Pin {data['bcm']}"),
            direction=PinDirection(str(data.get("direction", "input"))),
            pull=data.get("pull"),
            active_low=bool(data.get("active_low", True)),
            debounce_ms=int(data.get("debounce_ms", 200)),
            edge=PinEdge.from_str(data.get("edge")),
            enabled=bool(data.get("enabled", True)),
        )

    # ---- helpers ----

    def is_input(self) -> bool:
        return self.direction == PinDirection.INPUT

    def is_output(self) -> bool:
        return self.direction == PinDirection.OUTPUT

    def is_trigger(self) -> bool:
        """A pin is a trigger source if it's an enabled input with an edge set."""
        return self.is_input() and self.enabled and self.edge != PinEdge.NONE


__all__ = ["Pin", "PinDirection", "PinEdge"]
