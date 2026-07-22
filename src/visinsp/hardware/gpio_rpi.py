"""Real Raspberry Pi GPIO backend (RPi.GPIO).

This module imports :mod:`RPi.GPIO` lazily so it can be imported on
non-Pi machines without raising. The factory in :mod:`gpio_factory`
will only instantiate this backend when RPi.GPIO is actually available
and the host is a Raspberry Pi.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from ..models import Pin, PinDirection, PinEdge
from .gpio_backend import GpioBackend, PinState

log = logging.getLogger(__name__)

try:  # pragma: no cover - exercised on the Pi only
    import RPi.GPIO as GPIO  # type: ignore

    _RPI_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO = None  # type: ignore
    _RPI_AVAILABLE = False


class RpiGpio(GpioBackend):
    """GPIO backend using RPi.GPIO (BCM pin numbering)."""

    name = "rpi"

    def __init__(self) -> None:
        if not _RPI_AVAILABLE:
            raise RuntimeError("RPi.GPIO is not available on this system")
        self._lock = threading.RLock()
        self._pins: Dict[str, Pin] = {}
        self._last_level: Dict[str, int] = {}
        self._last_edge_at: Dict[str, float] = {}
        self._mode_set = False
        # Per-pin "edge fired" events consumed by wait_for_edge.
        self._edge_events: Dict[str, threading.Event] = {}
        self._edge_levels: Dict[str, int] = {}
        self._watcher: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- lifecycle ----

    def setup(self, pins: List[Pin]) -> None:
        with self._lock:
            if not self._mode_set:
                GPIO.setmode(GPIO.BCM)
                self._mode_set = True
            for pin in pins:
                self._setup_one(pin)
            self._stop.clear()
            if self._watcher is None or not self._watcher.is_alive():
                self._watcher = threading.Thread(
                    target=self._poll_loop, name="visinsp-rpi-gpio-poll", daemon=True
                )
                self._watcher.start()

    def _setup_one(self, pin: Pin) -> None:
        self._pins[pin.id] = pin
        self._edge_events[pin.id] = threading.Event()
        if pin.direction == PinDirection.INPUT:
            pud = GPIO.PUD_OFF
            if (pin.pull or "").lower() == "up":
                pud = GPIO.PUD_UP
            elif (pin.pull or "").lower() == "down":
                pud = GPIO.PUD_DOWN
            GPIO.setup(pin.bcm, GPIO.IN, pull_up_down=pud)
            self._last_level[pin.id] = int(GPIO.input(pin.bcm))
        else:
            GPIO.setup(pin.bcm, GPIO.OUT)
            initial = GPIO.LOW if not pin.active_low else GPIO.HIGH
            GPIO.output(pin.bcm, initial)
            self._last_level[pin.id] = int(initial)

    def cleanup(self) -> None:
        with self._lock:
            self._stop.set()
            if self._watcher:
                self._watcher.join(timeout=2.0)
                self._watcher = None
            if self._mode_set:
                try:
                    GPIO.cleanup()
                except RuntimeError:
                    pass
                self._mode_set = False
            self._pins.clear()
            self._edge_events.clear()
            self._edge_levels.clear()

    # ---- IO ----

    def read(self, pin_id: str) -> int:
        with self._lock:
            pin = self._pins[pin_id]
            return int(GPIO.input(pin.bcm))

    def write(self, pin_id: str, level: int) -> None:
        with self._lock:
            pin = self._pins[pin_id]
            if pin.direction != PinDirection.OUTPUT:
                raise ValueError(f"pin {pin_id} is not an output")
            GPIO.output(pin.bcm, GPIO.HIGH if level else GPIO.LOW)
            self._last_level[pin_id] = int(level)

    def wait_for_edge(
        self,
        pin_ids: List[str],
        timeout_s: Optional[float] = None,
    ) -> Optional[str]:
        # We poll on a small interval and let the background watcher push
        # edge events. RPi.GPIO's blocking wait_for_edge can only wait on
        # one pin and uses a busy-wait under the hood anyway, so polling
        # gives us "any-of-many" without the cost.
        deadline = time.monotonic() + timeout_s if timeout_s else None
        for pid in pin_ids:
            ev = self._edge_events.get(pid)
            if ev is not None:
                ev.clear()
        while True:
            for pid in pin_ids:
                ev = self._edge_events.get(pid)
                if ev is not None and ev.is_set():
                    ev.clear()
                    return pid
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    def get_states(self) -> List[PinState]:
        with self._lock:
            out: List[PinState] = []
            for pin in self._pins.values():
                try:
                    level = int(GPIO.input(pin.bcm))
                except RuntimeError:
                    level = self._last_level.get(pin.id, 0)
                self._last_level[pin.id] = level
                last_edge_at = self._last_edge_at.get(pin.id)
                last_edge = (
                    time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last_edge_at))
                    if last_edge_at
                    else None
                )
                out.append(
                    PinState(
                        id=pin.id,
                        bcm=pin.bcm,
                        name=pin.name,
                        direction=pin.direction.value,
                        level=level,
                        last_edge=last_edge,
                        last_edge_kind=None,
                        enabled=pin.enabled,
                    )
                )
            return out

    # ---- internal polling ----

    def _poll_loop(self) -> None:
        poll_interval = 0.01
        while not self._stop.is_set():
            with self._lock:
                pins_snapshot = list(self._pins.values())
            for pin in pins_snapshot:
                if not pin.enabled or pin.direction != PinDirection.INPUT:
                    continue
                if pin.edge == PinEdge.NONE:
                    continue
                try:
                    level = int(GPIO.input(pin.bcm))
                except RuntimeError:
                    continue
                prev = self._last_level.get(pin.id)
                if prev is None:
                    self._last_level[pin.id] = level
                    continue
                if level == prev:
                    continue
                # Debounce
                now = time.monotonic()
                last = self._last_edge_at.get(pin.id, 0.0)
                debounce_s = max(0, pin.debounce_ms) / 1000.0
                if (now - last) < debounce_s:
                    self._last_level[pin.id] = level
                    continue
                self._last_edge_at[pin.id] = now
                self._last_level[pin.id] = level
                if self.matches_edge(prev, level, pin.edge, pin.active_low):
                    self._edge_levels[pin.id] = level
                    ev = self._edge_events.get(pin.id)
                    if ev:
                        ev.set()
            time.sleep(poll_interval)


__all__ = ["RpiGpio"]
