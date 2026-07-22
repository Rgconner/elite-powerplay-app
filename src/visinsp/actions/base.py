"""Action base classes and registry."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from ..models import Action

log = logging.getLogger(__name__)

ActionContext = Dict[str, Any]
ActionHandler = Callable[[Action, ActionContext], None]


class ActionRegistry:
    """Maps an action ``type`` string to a handler function.

    Handlers are looked up by :class:`AlertManager` when an alert is
    raised or resolved. The registry is process-wide; tests can clear it.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: Dict[str, ActionHandler] = {}

    def register(self, type_name: str, handler: ActionHandler) -> None:
        with self._lock:
            self._handlers[type_name] = handler

    def unregister(self, type_name: str) -> None:
        with self._lock:
            self._handlers.pop(type_name, None)

    def get(self, type_name: str) -> ActionHandler:
        with self._lock:
            try:
                return self._handlers[type_name]
            except KeyError:
                raise KeyError(f"no action handler registered for type {type_name!r}")

    def has(self, type_name: str) -> bool:
        with self._lock:
            return type_name in self._handlers

    def types(self) -> list[str]:
        with self._lock:
            return list(self._handlers.keys())

    def clear(self) -> None:
        with self._lock:
            self._handlers.clear()


_default: Optional[ActionRegistry] = None
_default_lock = threading.Lock()


def get_action_registry() -> ActionRegistry:
    """Return the process-wide registry, creating it (and registering the
    default handlers) on first call.
    """
    global _default
    with _default_lock:
        if _default is None:
            from .gpio_action import GpioActionHandler
            from .notification_action import NotificationActionHandler
            from .sound_action import SoundActionHandler
            from .visual_action import VisualActionHandler

            _default = ActionRegistry()
            _default.register("gpio", GpioActionHandler())
            _default.register("sound", SoundActionHandler())
            _default.register("visual", VisualActionHandler())
            _default.register("notification", NotificationActionHandler())
            log.debug("action registry initialised with handlers: %s", _default.types())
        return _default


def reset_action_registry() -> None:
    """Drop the default registry (mostly for tests)."""
    global _default
    with _default_lock:
        _default = None


__all__ = ["ActionRegistry", "ActionHandler", "ActionContext", "get_action_registry", "reset_action_registry"]
