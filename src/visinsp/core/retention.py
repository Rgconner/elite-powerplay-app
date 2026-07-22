"""Retention worker.

Periodically prunes old captures, alerts, and threshold history rows
according to the configured retention windows. Runs in a daemon thread
that the application can stop on shutdown.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .state_store import StateStore

log = logging.getLogger(__name__)


class RetentionWorker:
    """Background thread that enforces data-retention rules."""

    def __init__(
        self,
        state: StateStore,
        captures_dir: Path,
        interval_s: int = 3600,
    ):
        self.state = state
        self.captures_dir = Path(captures_dir)
        self.interval_s = max(60, int(interval_s))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="visinsp-retention", daemon=True
        )
        self._thread.start()
        log.info("retention worker started (interval=%ds)", self.interval_s)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        log.info("retention worker stopped")

    # ---- internals ----

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep_once()
            except Exception:  # noqa: BLE001
                log.exception("retention sweep failed")
            # Wait, but break out early on stop.
            self._stop.wait(self.interval_s)

    def sweep_once(self) -> dict:
        """Run a single sweep pass; return a small summary dict for tests."""
        settings = self.state.get_settings()
        now = datetime.now()
        alert_cutoff = (now - timedelta(days=settings.retention_days)).isoformat(timespec="seconds")
        hist_cutoff = (now - timedelta(days=settings.history_retention_days)).isoformat(timespec="seconds")

        # ---- SQLite: drop old alerts + history rows ----
        deleted_alerts = 0
        deleted_history = 0
        with self.state._lock, self.state._connect() as conn:  # noqa: SLF001
            cur = conn.execute(
                "DELETE FROM alerts WHERE raised_at < ? AND verdict != 'pending'",
                (alert_cutoff,),
            )
            deleted_alerts = cur.rowcount or 0
            cur = conn.execute(
                "DELETE FROM threshold_history WHERE created_at < ?",
                (hist_cutoff,),
            )
            deleted_history = cur.rowcount or 0

        # ---- Filesystem: drop old capture JPEGs/PNGs ----
        deleted_captures = 0
        if self.captures_dir.exists():
            cutoff_ts = time.time() - (settings.retention_days * 86400)
            for p in self.captures_dir.iterdir():
                if not p.is_file():
                    continue
                if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                    continue
                try:
                    if p.stat().st_mtime < cutoff_ts:
                        p.unlink()
                        deleted_captures += 1
                except OSError as e:
                    log.debug("could not stat/delete %s: %s", p, e)

        if any([deleted_alerts, deleted_history, deleted_captures]):
            log.info(
                "retention: deleted %d alerts, %d history rows, %d captures",
                deleted_alerts, deleted_history, deleted_captures,
            )
        return {
            "alerts": deleted_alerts,
            "history": deleted_history,
            "captures": deleted_captures,
        }


__all__ = ["RetentionWorker"]
