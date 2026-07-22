"""Alert record model — the operator-facing unit of 'something was flagged'."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


class AlertVerdict(str, enum.Enum):
    """How the operator dismissed the alert.

    ``valid``           — the flag was correct, keep the threshold as-is.
    ``false_positive``  — flagged but the part was good; raise threshold.
    ``false_negative``  — not flagged but should have been; lower threshold.
    ``pending``         — not yet dismissed.
    """

    PENDING = "pending"
    VALID = "valid"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"

    @classmethod
    def from_str(cls, v: Optional[str]) -> "AlertVerdict":
        if not v:
            return cls.PENDING
        try:
            return cls(str(v).lower())
        except ValueError:
            return cls.PENDING

    def is_dismissed(self) -> bool:
        return self != AlertVerdict.PENDING


@dataclass
class AlertRecord:
    """An alert raised by a failed inspection.

    Carries the operator verdict once the alert is dismissed; the threshold
    auto-adjustment logic reads ``verdict`` to decide what to do.
    """

    id: str
    inspection_id: str
    job_id: str
    raised_at: str
    verdict: AlertVerdict = AlertVerdict.PENDING
    dismissed_at: Optional[str] = None
    notes: str = ""
    image_path: Optional[str] = None
    score: float = 0.0
    threshold: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "inspection_id": self.inspection_id,
            "job_id": self.job_id,
            "raised_at": self.raised_at,
            "verdict": self.verdict.value,
            "dismissed_at": self.dismissed_at,
            "notes": self.notes,
            "image_path": self.image_path,
            "score": float(self.score),
            "threshold": float(self.threshold),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertRecord":
        return cls(
            id=str(data.get("id") or f"alert_{uuid.uuid4().hex[:8]}"),
            inspection_id=str(data.get("inspection_id", "")),
            job_id=str(data.get("job_id", "")),
            raised_at=str(data.get("raised_at", "")),
            verdict=AlertVerdict.from_str(data.get("verdict")),
            dismissed_at=data.get("dismissed_at"),
            notes=str(data.get("notes", "")),
            image_path=data.get("image_path"),
            score=float(data.get("score", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
        )


__all__ = ["AlertRecord", "AlertVerdict"]
