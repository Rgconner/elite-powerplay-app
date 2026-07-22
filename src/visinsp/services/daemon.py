"""Main daemon: GPIO watch loop, inspection orchestration, retention.

The daemon:

1. Sets up the GPIO backend with the configured pins.
2. Sets up the action registry's GPIO backend reference.
3. Starts the retention worker.
4. Watches for edge events on input pins that are mapped to triggers.
5. For each fired trigger, runs the associated job and dispatches actions.
6. Periodically broadcasts the pin state over the event bus.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import List, Optional

from ..actions import set_gpio_backend
from ..config import Config, load_config
from ..core import AlertManager, InspectionEngine, RetentionWorker, StateStore
from ..core.event_bus import get_event_bus
from ..hardware import CameraManager, create_gpio_backend
from ..models import SecondaryMetric
from ..paths import Paths, ensure_data_dirs, resolve_paths

log = logging.getLogger(__name__)


class Daemon:
    """The main inspection daemon."""

    def __init__(self, config: Optional[Config] = None, paths: Optional[Paths] = None,
                 state: Optional[StateStore] = None,
                 gpio=None, cameras: Optional[CameraManager] = None,
                 engine: Optional[InspectionEngine] = None,
                 alerts: Optional[AlertManager] = None,
                 retention: Optional[RetentionWorker] = None):
        self.config = config or load_config()
        self.paths = paths or resolve_paths(self.config)
        ensure_data_dirs(self.paths)
        self.state = state or StateStore(self.paths.db_path)
        self.state.seed_pins_from_config(self.config.get("pins") or [])
        self.gpio = gpio or create_gpio_backend(self.config, persist_path=self.paths.mock_pins_path)
        self.cameras = cameras or CameraManager(self.config, self.paths)
        self.engine = engine or InspectionEngine(
            default_method=str(self.config.get("inspection.match_method", "TM_CCOEFF_NORMED")),
            max_image_dimension=int(self.config.get("inspection.max_image_dimension", 1280)),
        )
        self.alerts = alerts or AlertManager(self.state)
        self.retention = retention or RetentionWorker(
            self.state, self.paths.captures_dir,
            interval_s=max(60, int(self.config.get("alerts.retention_days", 30)) * 60),
        )
        self._stop = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None
        self._pin_broadcast_thread: Optional[threading.Thread] = None
        self.bus = get_event_bus()

    # ---- lifecycle ----

    def start(self) -> None:
        log.info("daemon: starting (env=%s, gpio=%s)",
                 self.config.get("app.environment"),
                 getattr(self.gpio, "name", "?"))
        # Set up pins
        pins = self.state.list_pins()
        self.gpio.setup(pins)
        # Wire action handlers
        set_gpio_backend(self.gpio)
        # Start retention
        self.retention.start()
        # Start GPIO watcher + pin broadcast
        self._stop.clear()
        self._watch_thread = threading.Thread(target=self._watch_loop, name="visinsp-gpio-watch", daemon=True)
        self._watch_thread.start()
        self._pin_broadcast_thread = threading.Thread(target=self._pin_broadcast_loop, name="visinsp-pin-bcast", daemon=True)
        self._pin_broadcast_thread.start()
        log.info("daemon: started")

    def stop(self, timeout: float = 5.0) -> None:
        log.info("daemon: stopping…")
        self._stop.set()
        for t in (self._watch_thread, self._pin_broadcast_thread):
            if t:
                t.join(timeout=timeout)
        try:
            self.retention.stop(timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.gpio.cleanup()
        except Exception:  # noqa: BLE001
            pass
        log.info("daemon: stopped")

    def run_forever(self) -> None:
        """Start, then block until SIGINT/SIGTERM."""
        self.start()
        stop = threading.Event()

        def _on_signal(signum, _frame):  # type: ignore[no-untyped-def]
            log.info("daemon: signal %s received", signum)
            stop.set()
            self._stop.set()

        try:
            signal.signal(signal.SIGINT, _on_signal)
            signal.signal(signal.SIGTERM, _on_signal)
        except (ValueError, OSError):
            # Not in the main thread (e.g. tests)
            pass

        try:
            while not stop.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ---- main loop ----

    def _watch_loop(self) -> None:
        """Wait for GPIO edges and run the matching job."""
        # Collect trigger pin ids
        trigger_pins: List[str] = list({
            t.pin_id for t in self.state.list_triggers() if t.enabled
        })
        # Also include any input pin configured with an edge, so we don't
        # miss triggers that haven't been persisted as a Trigger yet.
        for p in self.state.list_pins():
            if p.is_trigger() and p.id not in trigger_pins:
                trigger_pins.append(p.id)
        log.info("daemon: watching %d trigger pin(s): %s", len(trigger_pins), trigger_pins)

        while not self._stop.is_set():
            try:
                pin_id = self.gpio.wait_for_edge(trigger_pins, timeout_s=0.5)
            except Exception:  # noqa: BLE001
                log.exception("daemon: wait_for_edge raised")
                continue
            if not pin_id:
                continue
            self._handle_trigger(pin_id)

    def _handle_trigger(self, pin_id: str) -> None:
        log.info("daemon: trigger fired on pin %s", pin_id)
        triggers = [t for t in self.state.list_triggers_for_pin(pin_id) if t.enabled]
        if not triggers:
            log.info("daemon: no enabled trigger for pin %s", pin_id)
            return
        for t in triggers:
            job = self.state.get_job(t.job_id)
            if not job or not job.enabled:
                log.info("daemon: job %s not found or disabled", t.job_id)
                continue
            try:
                self._run_job(job, trigger_id=t.id)
            except Exception:  # noqa: BLE001
                log.exception("daemon: run_job failed for %s", job.id)

    def _run_job(self, job, trigger_id: Optional[str] = None) -> None:
        """Capture, inspect, raise alert if needed."""
        ref = self.state.get_reference(job.reference_id)
        if not ref or not ref.bboxes:
            log.warning("daemon: job %s has no usable reference / bboxes", job.id)
            return
        cap = self.cameras.capture(job.camera_id, save=True)
        if cap.get("frame") is None:
            log.warning("daemon: capture failed for camera %s", job.camera_id)
            return
        method = str(self.config.get("inspection.match_method", "TM_CCOEFF_NORMED"))
        secondary = SecondaryMetric.from_str(
            self.config.get("inspection.secondary_metric", "none")
        )
        result = self.engine.inspect(
            cap["frame"], ref, job, method=method, secondary=secondary,
            trigger_id=trigger_id, image_path=str(cap.get("path")) if cap.get("path") else None,
        )
        self.state.record_inspection(result)
        self.bus.publish("inspection_complete", result.to_dict())
        if not result.passed:
            self.alerts.raise_alert(result, job)
        else:
            self.alerts.record_pass(result, job)

    def _pin_broadcast_loop(self) -> None:
        while not self._stop.is_set():
            try:
                states = self.gpio.get_states()
                self.bus.publish("pin_state", {"states": [s.__dict__ for s in states]})
            except Exception:  # noqa: BLE001
                log.exception("daemon: pin broadcast raised")
            self._stop.wait(1.0)


def run() -> None:
    """CLI entry: start the daemon and block."""
    Daemon().run_forever()


__all__ = ["Daemon", "run"]
