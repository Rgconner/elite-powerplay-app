"""Visual action — emit a WebSocket event so the browser UI flashes."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from ..models import VisualAction

log = logging.getLogger(__name__)

# The emitter should be `socketio.emit(event, data)`. Set at app startup.
_emitter_holder: Dict[str, Any] = {"emitter": None}
_holder_lock = threading.Lock()


def set_visual_emitter(emitter: Optional[Callable[[str, Any], None]]) -> None:
    with _holder_lock:
        _emitter_holder["emitter"] = emitter


def get_visual_emitter() -> Optional[Callable[[str, Any], None]]:
    with _holder_lock:
        return _emitter_holder.get("emitter")


class VisualActionHandler:
    """Push a ``visual_flash`` WebSocket event."""

    def __call__(self, action: VisualAction, context: Dict[str, Any]) -> None:
        emitter = get_visual_emitter()
        payload = {
            "color": action.color or "red",
            "duration_ms": int(action.duration_ms or 1500),
            "message": action.message or "",
            "context": {
                k: v for k, v in context.items()
                if k in ("alert_id", "inspection_id", "job_id", "kind")
            },
        }
        if emitter is None:
            log.debug("visual_action: no emitter wired; would have sent %s", payload)
            return
        try:
            emitter("visual_flash", payload)
        except Exception:  # noqa: BLE001
            log.exception("visual_action: emitter raised")
        log.info("visual_action: %s %dms", payload["color"], payload["duration_ms"])


__all__ = ["VisualActionHandler", "set_visual_emitter", "get_visual_emitter"]
