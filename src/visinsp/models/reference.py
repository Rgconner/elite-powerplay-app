"""Reference image + bounding box model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BoundingBox:
    """A user-drawn rectangle in the reference image (pixel coords)."""

    id: str
    x: int
    y: int
    w: int
    h: int
    label: str = ""
    weight: float = 1.0

    def clamp_to(self, width: int, height: int) -> "BoundingBox":
        """Return a copy with coordinates clipped to the image bounds."""
        x2 = min(self.x + self.w, width)
        y2 = min(self.y + self.h, height)
        x1 = max(0, min(self.x, width - 1))
        y1 = max(0, min(self.y, height - 1))
        return BoundingBox(
            id=self.id,
            x=x1,
            y=y1,
            w=max(1, x2 - x1),
            h=max(1, y2 - y1),
            label=self.label,
            weight=self.weight,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x": int(self.x),
            "y": int(self.y),
            "w": int(self.w),
            "h": int(self.h),
            "label": self.label,
            "weight": float(self.weight),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        return cls(
            id=str(data.get("id") or f"bb_{uuid.uuid4().hex[:8]}"),
            x=int(data["x"]),
            y=int(data["y"]),
            w=int(data["w"]),
            h=int(data["h"]),
            label=str(data.get("label", "")),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass
class ReferenceImage:
    """A stored reference image and its associated bounding boxes."""

    id: str
    name: str
    camera_id: str
    image_path: str
    width: int = 0
    height: int = 0
    created_at: Optional[str] = None
    bboxes: List[BoundingBox] = field(default_factory=list)
    notes: str = ""

    # ---- serialisation ----

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "camera_id": self.camera_id,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "notes": self.notes,
            "bboxes": [b.to_dict() for b in self.bboxes],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReferenceImage":
        return cls(
            id=str(data.get("id") or f"ref_{uuid.uuid4().hex[:8]}"),
            name=str(data.get("name", "Unnamed reference")),
            camera_id=str(data.get("camera_id", "cam_0")),
            image_path=str(data["image_path"]),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            created_at=data.get("created_at"),
            notes=str(data.get("notes", "")),
            bboxes=[BoundingBox.from_dict(b) for b in (data.get("bboxes") or [])],
        )


__all__ = ["BoundingBox", "ReferenceImage"]
