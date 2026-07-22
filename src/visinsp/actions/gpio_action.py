"""GPIO output action — drive an output pin HIGH/LOW/pulse."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from ..models import GpioAction

log = logging.getLogger(__name__)

_gpio_backend_holder: Dict[str, Any] = {"backend": None}
_holder_lock = threading.Lock()


def set_gpio_backend(backend) -> None:
    """Inject the GPIO backend (called by the daemon at startup)."""
    with _holder_lock:
        _gpio_backend_holder["backend"] = backend


def get_gpio_backend():
    with _holder_lock:
        return _gpio_backend_holder.get("backend")


class GpioActionHandler:
    """Drive an output pin according to a :class:`GpioAction`."""

    def __call__(self, action: GpioAction, context: Dict[str, Any]) -> None:
        backend = get_gpio_backend()
        if backend is None:
            log.warning("gpio_action: no backend available; skipping %s", action)
            return
        pin_id = action.pin_id
        if not pin_id:
            log.warning("gpio_action: missing pin_id; skipping")
            return
        mode = (action.mode or "HIGH").upper()
        try:
            if mode == "HIGH":
                backend.write(pin_id, 1)
            elif mode == "LOW":
                backend.write(pin_id, 0)
            elif mode == "PULSE":
                duration = max(0, int(action.duration_ms)) / 1000.0
                backend.write(pin_id, 1)
                time.sleep(duration)
                backend.write(pin_id, 0)
            else:
                log.warning("gpio_action: unknown mode %r", mode)
                return
            log.info("gpio_action: pin=%s mode=%s context=%s",
                     pin_id, mode, {k: v for k, v in context.items() if k in ("alert_id", "job_id")})
        except Exception:  # noqa: BLE001
            log.exception("gpio_action: failed for pin=%s mode=%s", pin_id, mode)


__all__ = ["GpioActionHandler", "set_gpio_backend", "get_gpio_backend"]
