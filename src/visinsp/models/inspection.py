"""Inspection result model — per-box + overall scores for one trigger event."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class SecondaryMetric(str, enum.Enum):
    NONE = "none"
    MSE = "MSE"
    SSIM = "SSIM"

    @classmethod
    def from_str(cls, v: Optional[str]) -> "SecondaryMetric":
        if not v:
            return cls.NONE
        try:
            return cls(str(v).upper())
        except ValueError:
            return cls.NONE


@dataclass
class BBoxScore:
    """Comparison score for a single bounding box."""

    bbox_id: str
    score: float
    method: str = "TM_CCOEFF_NORMED"
    secondary: Optional[float] = None  # MSE / SSIM if requested
    secondary_metric: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bbox_id": self.bbox_id,
            "score": float(self.score),
            "method": self.method,
            "secondary": self.secondary,
            "secondary_metric": self.secondary_metric,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BBoxScore":
        return cls(
            bbox_id=str(data["bbox_id"]),
            score=float(data.get("score", 0.0)),
            method=str(data.get("method", "TM_CCOEFF_NORMED")),
            secondary=(float(data["secondary"]) if data.get("secondary") is not None else None),
            secondary_metric=str(data.get("secondary_metric", "none")),
        )


def compute_overall_score(per_box: List["BBoxScore"], weights: Dict[str, float]) -> float:
    """Compute a weighted-mean overall score from per-box scores.

    If no boxes, returns 1.0 (vacuous pass).
    """
    if not per_box:
        return 1.0
    total_w = 0.0
    total_v = 0.0
    for s in per_box:
        w = float(weights.get(s.bbox_id, 1.0))
        if w <= 0:
            continue
        total_v += s.score * w
        total_w += w
    if total_w == 0:
        return 0.0
    return total_v / total_w


@dataclass
class InspectionResult:
    """One inspection run (one trigger)."""

    id: str
    job_id: str
    trigger_id: Optional[str]
    captured_at: str
    score_overall: float
    threshold: float
    passed: bool
    per_box: List[BBoxScore] = field(default_factory=list)
    image_path: Optional[str] = None
    match_method: str = "TM_CCOEFF_NORMED"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "trigger_id": self.trigger_id,
            "captured_at": self.captured_at,
            "score_overall": float(self.score_overall),
            "threshold": float(self.threshold),
            "passed": bool(self.passed),
            "per_box": [b.to_dict() for b in self.per_box],
            "image_path": self.image_path,
            "match_method": self.match_method,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InspectionResult":
        return cls(
            id=str(data.get("id") or f"insp_{uuid.uuid4().hex[:8]}"),
            job_id=str(data["job_id"]),
            trigger_id=data.get("trigger_id"),
            captured_at=str(data.get("captured_at", "")),
            score_overall=float(data.get("score_overall", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
            passed=bool(data.get("passed", False)),
            per_box=[BBoxScore.from_dict(b) for b in (data.get("per_box") or [])],
            image_path=data.get("image_path"),
            match_method=str(data.get("match_method", "TM_CCOEFF_NORMED")),
            notes=str(data.get("notes", "")),
        )


__all__ = [
    "BBoxScore",
    "InspectionResult",
    "SecondaryMetric",
    "compute_overall_score",
]
