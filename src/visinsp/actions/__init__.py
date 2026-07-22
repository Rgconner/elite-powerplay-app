"""Action handlers.

Each action type (GPIO, sound, visual, notification) has a small handler
function that takes an :class:`~visinsp.models.Action` subclass and a
context dict. The handlers are registered in a process-wide registry
that the alert manager looks up by action type.
"""

from .base import ActionContext, ActionHandler, ActionRegistry, get_action_registry
from .gpio_action import GpioActionHandler, set_gpio_backend
from .notification_action import NotificationActionHandler, set_socketio_emitter
from .sound_action import SoundActionHandler
from .visual_action import VisualActionHandler, set_visual_emitter

__all__ = [
    "ActionContext",
    "ActionHandler",
    "ActionRegistry",
    "get_action_registry",
    "GpioActionHandler",
    "set_gpio_backend",
    "SoundActionHandler",
    "VisualActionHandler",
    "set_visual_emitter",
    "NotificationActionHandler",
    "set_socketio_emitter",
]
