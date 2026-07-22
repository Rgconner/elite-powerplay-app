"""Job model — a runnable unit of inspection tied to a reference and threshold."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .action import Action, actions_from_dicts, actions_to_dicts


@dataclass
class Job:
    """One inspection job: reference + camera + threshold + actions."""

    id: str
    name: str
    reference_id: str
    camera_id: str
    threshold: float = 0.85
    threshold_step: float = 0.005
    enabled: bool = True
    actions_on_fail: List[Action] = field(default_factory=list)
    actions_on_pass: List[Action] = field(default_factory=list)
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ---- serialisation ----

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "reference_id": self.reference_id,
            "camera_id": self.camera_id,
            "threshold": float(self.threshold),
            "threshold_step": float(self.threshold_step),
            "enabled": bool(self.enabled),
            "actions_on_fail": actions_to_dicts(self.actions_on_fail),
            "actions_on_pass": actions_to_dicts(self.actions_on_pass),
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        return cls(
            id=str(data.get("id") or f"job_{uuid.uuid4().hex[:8]}"),
            name=str(data.get("name", "Untitled job")),
            reference_id=str(data.get("reference_id", "")),
            camera_id=str(data.get("camera_id", "cam_0")),
            threshold=float(data.get("threshold", 0.85)),
            threshold_step=float(data.get("threshold_step", 0.005)),
            enabled=bool(data.get("enabled", True)),
            actions_on_fail=actions_from_dicts(data.get("actions_on_fail") or []),
            actions_on_pass=actions_from_dicts(data.get("actions_on_pass") or []),
            notes=str(data.get("notes", "")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


__all__ = ["Job"]
