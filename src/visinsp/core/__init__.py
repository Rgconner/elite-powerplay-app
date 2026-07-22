"""Core business logic for Visual Inspector.

This package contains the platform-agnostic pieces: SQLite state store,
in-process event bus, threshold auto-adjustment, image-inspection engine,
alert manager, and retention. It deliberately knows nothing about GPIO or
the web UI — those are pluggable concerns.
"""

from .alert_manager import AlertManager
from .event_bus import EventBus, get_event_bus
from .inspection_engine import InspectionEngine
from .retention import RetentionWorker
from .state_store import StateStore
from .threshold import apply_verdict, clamp_threshold

__all__ = [
    "AlertManager",
    "EventBus",
    "get_event_bus",
    "InspectionEngine",
    "RetentionWorker",
    "StateStore",
    "apply_verdict",
    "clamp_threshold",
]
