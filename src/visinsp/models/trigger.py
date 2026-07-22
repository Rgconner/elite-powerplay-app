"""Trigger model — a link between an input pin and a job to run on edge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .pin import PinEdge


@dataclass
class Trigger:
    """A mapping of an input pin + edge to a job."""

    id: str
    pin_id: str
    job_id: str
    edge: PinEdge = PinEdge.FALLING
    enabled: bool = True
    name: Optional[str] = None

    # ---- serialisation ----

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pin_id": self.pin_id,
            "job_id": self.job_id,
            "edge": self.edge.value,
            "enabled": self.enabled,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trigger":
        return cls(
            id=str(data.get("id") or f"trig_{uuid.uuid4().hex[:8]}"),
            pin_id=str(data["pin_id"]),
            job_id=str(data["job_id"]),
            edge=PinEdge.from_str(data.get("edge", "falling")),
            enabled=bool(data.get("enabled", True)),
            name=data.get("name"),
        )


__all__ = ["Trigger"]
