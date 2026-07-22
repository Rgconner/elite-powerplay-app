"""Mock GPIO backend for WSL / dev mode.

Keeps an in-memory dict of pin levels, persists it to
``data/mock_pins.json`` so restarts keep state, and exposes
``simulate_edge`` so the UI's "press button" button can drive the
daemon like a real trigger would.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Pin, PinDirection, PinEdge
from .gpio_backend import GpioBackend, PinState

log = logging.getLogger(__name__)


class GpioMock(GpioBackend):
    """In-process GPIO simulator. No hardware needed."""

    name = "mock"

    def __init__(self, persist_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._pins: Dict[str, Pin] = {}
        self._levels: Dict[str, int] = {}
        self._last_edge_at: Dict[str, float] = {}
        self._last_edge_kind: Dict[str, str] = {}
        self._edge_events: Dict[str, threading.Event] = {}
        self._persist_path: Optional[Path] = Path(persist_path) if persist_path else None
        if self._persist_path and self._persist_path.exists():
            try:
                self._load_persisted()
            except (OSError, json.JSONDecodeError) as e:
                log.warning("mock: could not load %s: %s", self._persist_path, e)

    # ---- persistence ----

    def _load_persisted(self) -> None:
        if not self._persist_path:
            return
        with open(self._persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pin_id, payload in (data.get("pins") or {}).items():
            self._levels[pin_id] = int(payload.get("level", 0))

    def _persist(self) -> None:
        if not self._persist_path:
            return
        payload = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pins": {pid: {"level": lvl} for pid, lvl in self._levels.items()},
        }
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(self._persist_path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp.replace(self._persist_path)
        except OSError as e:
            log.warning("mock: could not persist to %s: %s", self._persist_path, e)

    # ---- lifecycle ----

    def setup(self, pins: List[Pin]) -> None:
        with self._lock:
            for pin in pins:
                self._pins[pin.id] = pin
                # Default level: HIGH for active-low inputs (matches Pi behaviour with pull-up)
                if pin.id not in self._levels:
                    if pin.direction == PinDirection.INPUT and pin.active_low:
                        self._levels[pin.id] = 1
                    else:
                        self._levels[pin.id] = 0
                self._edge_events[pin.id] = threading.Event()
            self._persist()

    def cleanup(self) -> None:
        with self._lock:
            self._persist()
            self._pins.clear()
            self._edge_events.clear()

    # ---- IO ----

    def read(self, pin_id: str) -> int:
        with self._lock:
            return int(self._levels.get(pin_id, 0))

    def write(self, pin_id: str, level: int) -> None:
        with self._lock:
            pin = self._pins.get(pin_id)
            if pin and pin.direction != PinDirection.OUTPUT:
                raise ValueError(f"pin {pin_id} is not an output")
            self._levels[pin_id] = 1 if level else 0
            self._persist()

    def wait_for_edge(
        self,
        pin_ids: List[str],
        timeout_s: Optional[float] = None,
    ) -> Optional[str]:
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
                level = int(self._levels.get(pin.id, 0))
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
                        last_edge_kind=self._last_edge_kind.get(pin.id),
                        enabled=pin.enabled,
                    )
                )
            return out

    # ---- mock-only helpers ----

    def simulate_edge(self, pin_id: str, level: int) -> None:
        """Inject a level change (called by the UI / API)."""
        with self._lock:
            pin = self._pins.get(pin_id)
            if not pin:
                log.warning("mock: simulate_edge on unknown pin %s", pin_id)
                return
            if pin.direction != PinDirection.INPUT:
                log.warning("mock: simulate_edge on non-input pin %s", pin_id)
                return
            self._inject(pin, int(level))

    def set_mock_level(self, pin_id: str, level: int) -> None:
        """Set the level directly (no edge event fires)."""
        with self._lock:
            self._levels[pin_id] = 1 if level else 0
            self._persist()

    def toggle(self, pin_id: str) -> int:
        """Flip the pin level and fire an edge (for the UI button)."""
        with self._lock:
            pin = self._pins.get(pin_id)
            if not pin:
                raise KeyError(pin_id)
            new_level = 0 if self._levels.get(pin.id, 0) else 1
            self._inject(pin, new_level)
            return new_level

    # ---- internals ----

    def _inject(self, pin: Pin, new_level: int) -> None:
        prev = self._levels.get(pin.id, 0)
        now = time.monotonic()
        last = self._last_edge_at.get(pin.id, 0.0)
        debounce_s = max(0, pin.debounce_ms) / 1000.0
        if (now - last) < debounce_s:
            self._levels[pin.id] = new_level
            return
        self._levels[pin.id] = new_level
        self._last_edge_at[pin.id] = now
        if prev != new_level:
            self._last_edge_kind[pin.id] = "rising" if new_level == 1 else "falling"
            if self.matches_edge(prev, new_level, pin.edge, pin.active_low):
                ev = self._edge_events.get(pin.id)
                if ev:
                    ev.set()
        self._persist()


__all__ = ["GpioMock"]
