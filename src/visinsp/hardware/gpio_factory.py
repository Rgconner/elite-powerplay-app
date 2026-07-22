"""GPIO backend factory.

Picks the right backend at runtime based on the config and what the host
actually supports:

* ``force_backend: "mock"``   → always :class:`GpioMock`.
* ``force_backend: "pi"``     → require :class:`RpiGpio`; error if not available.
* ``force_backend: null``     → auto-detect (Pi if RPi.GPIO is importable
  and we're on a Pi, otherwise Mock).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .gpio_backend import GpioBackend
from .gpio_mock import GpioMock
from .gpio_rpi import RpiGpio, _RPI_AVAILABLE  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)


def _is_raspberry_pi() -> bool:
    """Best-effort detection of a Raspberry Pi host."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            if "Raspberry Pi" in f.read():
                return True
    except OSError:
        pass
    try:
        with open("/proc/device-tree/model", "r") as f:
            if "Raspberry Pi" in f.read():
                return True
    except OSError:
        pass
    return False


def get_active_backend_name(config) -> str:
    """Return the backend name (``"rpi"`` or ``"mock"``) the factory would pick."""
    forced = (config.get("environment.force_backend") or "").lower() or None
    if forced == "mock":
        return "mock"
    if forced == "pi":
        return "rpi" if _RPI_AVAILABLE else "mock"
    if _RPI_AVAILABLE and _is_raspberry_pi():
        return "rpi"
    return "mock"


def create_gpio_backend(config, persist_path: Optional[Path] = None) -> GpioBackend:
    """Create the appropriate :class:`GpioBackend` for this host/config."""
    name = get_active_backend_name(config)
    log.info("gpio backend selected: %s", name)
    if name == "rpi":
        return RpiGpio()
    return GpioMock(persist_path=persist_path)


__all__ = ["create_gpio_backend", "get_active_backend_name"]
