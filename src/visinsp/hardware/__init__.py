"""Hardware abstraction layer.

Two interfaces are defined:

* :class:`GpioBackend`     — read / write / watch GPIO pins.
* :class:`CameraManager`   — enumerate and capture from attached cameras.

The factory in :mod:`gpio_factory` picks the right backend at runtime
based on the config and what the host can actually import.
"""

from .camera_manager import CameraInfo, CameraManager
from .gpio_backend import GpioBackend, GpioState, PinState
from .gpio_factory import create_gpio_backend, get_active_backend_name
from .gpio_mock import GpioMock
from .gpio_rpi import RpiGpio

__all__ = [
    "GpioBackend",
    "GpioState",
    "PinState",
    "RpiGpio",
    "GpioMock",
    "create_gpio_backend",
    "get_active_backend_name",
    "CameraManager",
    "CameraInfo",
]
