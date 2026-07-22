"""In-process pub/sub used to decouple modules.

Today everything runs in one process, so this is just a synchronous
dispatcher. The interface is small enough that we can later swap it for a
real broker (Redis, ZeroMQ, HTTP webhooks) without changing call sites:

    bus = get_event_bus()
    bus.subscribe("pin_state", my_handler)
    bus.publish("pin_state", {"pin_id": "trigger_1", "level": 0})
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict, List

log = logging.getLogger(__name__)

# A handler receives the event payload (dict) and returns nothing.
Handler = Callable[[str, Any], None]


class EventBus:
    """Simple synchronous event bus with thread-safe subscribe/publish."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: DefaultDict[str, List[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subs[topic].append(handler)
        log.debug("event_bus: subscribed %s to %r", handler, topic)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs.get(topic, []):
                self._subs[topic].remove(handler)

    def publish(self, topic: str, payload: Any = None) -> None:
        # Snapshot under lock, dispatch outside the lock so handlers can
        # call back into the bus without deadlocking.
        with self._lock:
            handlers = list(self._subs.get(topic, ()))
        for h in handlers:
            try:
                h(topic, payload)
            except Exception:  # noqa: BLE001
                log.exception("event_bus: handler %r for %r raised", h, topic)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()


_default_bus: EventBus | None = None
_default_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide :class:`EventBus` (created on first call)."""
    global _default_bus
    with _default_lock:
        if _default_bus is None:
            _default_bus = EventBus()
        return _default_bus


def reset_event_bus() -> None:
    """Drop the default bus — useful in tests."""
    global _default_bus
    with _default_lock:
        _default_bus = None


__all__ = ["EventBus", "Handler", "get_event_bus", "reset_event_bus"]
