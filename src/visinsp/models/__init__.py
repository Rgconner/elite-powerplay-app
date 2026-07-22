"""Data models for Visual Inspector.

Each model is a plain dataclass with ``to_dict`` / ``from_dict`` methods so
the SQLite state store and the JSON API can share a single serialisation
format.

Importing from this package is cheap (no OpenCV, no Flask).
"""

from .action import (
    Action,
    GpioAction,
    NotificationAction,
    SoundAction,
    VisualAction,
    action_from_dict,
)
from .alert import AlertRecord, AlertVerdict
from .inspection import (
    BBoxScore,
    InspectionResult,
    SecondaryMetric,
    compute_overall_score,
)
from .job import Job
from .pin import Pin, PinDirection, PinEdge
from .reference import BoundingBox, ReferenceImage
from .settings import Settings
from .trigger import Trigger

__all__ = [
    "Action",
    "GpioAction",
    "NotificationAction",
    "SoundAction",
    "VisualAction",
    "action_from_dict",
    "AlertRecord",
    "AlertVerdict",
    "BBoxScore",
    "InspectionResult",
    "SecondaryMetric",
    "compute_overall_score",
    "Job",
    "Pin",
    "PinDirection",
    "PinEdge",
    "BoundingBox",
    "ReferenceImage",
    "Settings",
    "Trigger",
]
