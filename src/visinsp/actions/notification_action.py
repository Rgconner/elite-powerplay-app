"""Notification action — push a toast-style event over WebSocket."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from ..models import NotificationAction

log = logging.getLogger(__name__)

_emitter_holder: Dict[str, Any] = {"emitter": None}
_holder_lock = threading.Lock()


def set_socketio_emitter(emitter: Optional[Callable[[str, Any], None]]) -> None:
    with _holder_lock:
        _emitter_holder["emitter"] = emitter


def get_socketio_emitter() -> Optional[Callable[[str, Any], None]]:
    with _holder_lock:
        return _emitter_holder.get("emitter")


class NotificationActionHandler:
    """Push a ``notification`` WebSocket event so the UI shows a toast."""

    def __call__(self, action: NotificationAction, context: Dict[str, Any]) -> None:
        emitter = get_socketio_emitter()
        payload = {
            "title": action.title or "Inspection Alert",
            "body": action.body or "",
            "kind": action.kind or "error",
            "context": {
                k: v for k, v in context.items()
                if k in ("alert_id", "inspection_id", "job_id", "kind")
            },
        }
        if emitter is None:
            log.debug("notification_action: no emitter wired; would have sent %s", payload)
            return
        try:
            emitter("notification", payload)
        except Exception:  # noqa: BLE001
            log.exception("notification_action: emitter raised")
        log.info("notification_action: %s — %s", payload["title"], payload["body"])


__all__ = ["NotificationActionHandler", "set_socketio_emitter", "get_socketio_emitter"]
