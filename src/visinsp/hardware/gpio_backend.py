"""GPIO backend abstract base class + small helper types."""

from __future__ import annotations

import abc
import enum
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..models import Pin, PinEdge

log = logging.getLogger(__name__)


class GpioState(enum.Enum):
    """Reported high-level state of a pin (after active-low / pull-up adjustment)."""

    LOW = 0
    HIGH = 1


@dataclass
class PinState:
    """Runtime state of a pin, used for the dashboard."""

    id: str
    bcm: int
    name: str
    direction: str
    level: int  # 0 or 1
    last_edge: Optional[str] = None  # human-readable last edge time
    last_edge_kind: Optional[str] = None  # "rising" | "falling" | None
    enabled: bool = True


class GpioBackend(abc.ABC):
    """Abstract interface every GPIO backend must implement."""

    name: str = "abstract"

    # ---- lifecycle ----

    @abc.abstractmethod
    def setup(self, pins: List[Pin]) -> None:
        """Initialise all pins according to their config."""

    @abc.abstractmethod
    def cleanup(self) -> None:
        """Release any resources. Always safe to call twice."""

    # ---- synchronous IO ----

    @abc.abstractmethod
    def read(self, pin_id: str) -> int:
        """Return the current raw level of the pin (0 or 1)."""

    @abc.abstractmethod
    def write(self, pin_id: str, level: int) -> None:
        """Drive an output pin to ``level`` (0 or 1)."""

    # ---- edge waiting (used by the daemon main loop) ----

    @abc.abstractmethod
    def wait_for_edge(
        self,
        pin_ids: List[str],
        timeout_s: Optional[float] = None,
    ) -> Optional[str]:
        """Block until any of ``pin_ids`` sees the configured edge.

        Returns the pin id that fired, or ``None`` on timeout. Backend
        implementations may debounce internally based on the pin's
        configured ``debounce_ms``.
        """

    # ---- introspection (used by the web UI) ----

    @abc.abstractmethod
    def get_states(self) -> List[PinState]:
        """Return a snapshot of the state of every pin."""

    # ---- mock-only hooks (real backends raise NotImplementedError) ----

    def simulate_edge(self, pin_id: str, level: int) -> None:
        """Mock-only helper: inject a level change."""
        raise NotImplementedError(f"{self.name} does not support simulate_edge")

    def set_mock_level(self, pin_id: str, level: int) -> None:
        """Mock-only helper: set the level directly (no edge event)."""
        raise NotImplementedError(f"{self.name} does not support set_mock_level")

    # ---- convenience for subclasses ----

    @staticmethod
    def matches_edge(prev: Optional[int], curr: int, edge: PinEdge, active_low: bool) -> bool:
        """Return True if a transition from prev→curr matches the edge.

        ``active_low`` flips the meaning so a logical 0/1 maps to the
        same edge name in the user's mind (a 'falling' edge means the
        switch *closed*, regardless of how it's wired).
        """
        if prev is None:
            return False
        # Normalise to "logical" (1 = active) by flipping for active-low.
        p = (1 - prev) if active_low else prev
        c = (1 - curr) if active_low else curr
        if p == c:
            return False
        rising = (p == 0 and c == 1)
        if edge == PinEdge.BOTH:
            return True
        if edge == PinEdge.RISING:
            return rising
        if edge == PinEdge.FALLING:
            return not rising
        return False


__all__ = ["GpioBackend", "GpioState", "PinState"]
