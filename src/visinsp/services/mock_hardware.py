"""Helpers for driving the mock GPIO from scripts / tests.

These let you trigger a pin edge programmatically without going through
the HTTP API.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..hardware import GpioMock

log = logging.getLogger(__name__)


def tick(gpio: Optional[GpioMock] = None, pin_id: Optional[str] = None, level: int = 0) -> None:
    """Inject an edge into the (mock) GPIO backend.

    If ``gpio`` is None, this is a no-op (so the import is harmless on
    a real Pi).
    """
    if gpio is None:
        return
    if pin_id is None:
        return
    if not isinstance(gpio, GpioMock):
        log.warning("mock_hardware.tick: backend is not a mock; ignoring")
        return
    gpio.simulate_edge(pin_id, level)


__all__ = ["tick"]
