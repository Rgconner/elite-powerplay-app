"""SQLite state store for Visual Inspector.

A single SQLite file (no separate server) holds every entity the app
needs: pins, triggers, references, jobs, inspection results, alerts,
settings, and threshold history. All public methods are thread-safe and
use short-lived connections from a per-thread pool.

The schema is created on first use (``ensure_schema``) and is additive —
if you add a column you must also bump :data:`SCHEMA_VERSION` and add the
column to ``ensure_schema``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..models import (
    AlertRecord,
    AlertVerdict,
    BoundingBox,
    InspectionResult,
    Job,
    Pin,
    PinDirection,
    PinEdge,
    ReferenceImage,
    Settings,
    Trigger,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# DDL is split per table so migrations are easier to add later.
_SCHEMA: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pins (
        id TEXT PRIMARY KEY,
        bcm INTEGER NOT NULL,
        name TEXT NOT NULL,
        direction TEXT NOT NULL,
        pull TEXT,
        active_low INTEGER NOT NULL DEFAULT 1,
        debounce_ms INTEGER NOT NULL DEFAULT 200,
        edge TEXT NOT NULL DEFAULT 'none',
        enabled INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS triggers (
        id TEXT PRIMARY KEY,
        pin_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        edge TEXT NOT NULL DEFAULT 'falling',
        enabled INTEGER NOT NULL DEFAULT 1,
        name TEXT,
        FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS references (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        camera_id TEXT NOT NULL,
        image_path TEXT NOT NULL,
        width INTEGER NOT NULL DEFAULT 0,
        height INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        notes TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bboxes (
        id TEXT PRIMARY KEY,
        reference_id TEXT NOT NULL,
        x INTEGER NOT NULL,
        y INTEGER NOT NULL,
        w INTEGER NOT NULL,
        h INTEGER NOT NULL,
        label TEXT DEFAULT '',
        weight REAL NOT NULL DEFAULT 1.0,
        FOREIGN KEY (reference_id) REFERENCES references(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        reference_id TEXT NOT NULL,
        camera_id TEXT NOT NULL,
        threshold REAL NOT NULL DEFAULT 0.85,
        threshold_step REAL NOT NULL DEFAULT 0.005,
        enabled INTEGER NOT NULL DEFAULT 1,
        actions_on_fail TEXT NOT NULL DEFAULT '[]',
        actions_on_pass TEXT NOT NULL DEFAULT '[]',
        notes TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (reference_id) REFERENCES references(id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inspections (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        trigger_id TEXT,
        captured_at TEXT NOT NULL,
        score_overall REAL NOT NULL,
        threshold REAL NOT NULL,
        passed INTEGER NOT NULL,
        per_box TEXT NOT NULL DEFAULT '[]',
        image_path TEXT,
        match_method TEXT DEFAULT 'TM_CCOEFF_NORMED',
        notes TEXT DEFAULT '',
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        inspection_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        raised_at TEXT NOT NULL,
        verdict TEXT NOT NULL DEFAULT 'pending',
        dismissed_at TEXT,
        notes TEXT DEFAULT '',
        image_path TEXT,
        score REAL NOT NULL DEFAULT 0.0,
        threshold REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS threshold_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        old_value REAL NOT NULL,
        new_value REAL NOT NULL,
        reason TEXT NOT NULL,
        alert_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        id TEXT PRIMARY KEY,
        default_threshold REAL NOT NULL DEFAULT 0.85,
        default_threshold_step REAL NOT NULL DEFAULT 0.005,
        min_threshold REAL NOT NULL DEFAULT 0.50,
        max_threshold REAL NOT NULL DEFAULT 0.99,
        retention_days INTEGER NOT NULL DEFAULT 30,
        history_retention_days INTEGER NOT NULL DEFAULT 90,
        theme TEXT NOT NULL DEFAULT 'g100',
        auto_dismiss_after_hours INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_triggers_pin    ON triggers(pin_id)",
    "CREATE INDEX IF NOT EXISTS idx_bboxes_ref     ON bboxes(reference_id)",
    "CREATE INDEX IF NOT EXISTS idx_inspect_job    ON inspections(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_job     ON alerts(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_verdict ON alerts(verdict)",
    "CREATE INDEX IF NOT EXISTS idx_history_job    ON threshold_history(job_id)",
]


class StateStore:
    """Thread-safe SQLite-backed state store.

    Connections are created lazily per call (sqlite3 connections aren't
    safe to share across threads without a lock, and the cost of opening
    one is negligible compared to the inspection work).
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False
        self.ensure_schema()

    # ---- connection / schema ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,  # autocommit; we use explicit BEGIN
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
                row = cur.fetchone()
                current = int(row["version"]) if row else 0
                for stmt in _SCHEMA:
                    conn.execute(stmt)
                if current == 0:
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
                elif current < SCHEMA_VERSION:
                    # Future: run per-version migrations here.
                    conn.execute(
                        "UPDATE schema_version SET version = ?",
                        (SCHEMA_VERSION,),
                    )
                self._initialized = True
            finally:
                conn.close()

    # ---- pins ----

    def upsert_pin(self, pin: Pin) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pins(id, bcm, name, direction, pull, active_low, debounce_ms, edge, enabled)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    bcm=excluded.bcm,
                    name=excluded.name,
                    direction=excluded.direction,
                    pull=excluded.pull,
                    active_low=excluded.active_low,
                    debounce_ms=excluded.debounce_ms,
                    edge=excluded.edge,
                    enabled=excluded.enabled
                """,
                (
                    pin.id,
                    pin.bcm,
                    pin.name,
                    pin.direction.value,
                    pin.pull,
                    1 if pin.active_low else 0,
                    pin.debounce_ms,
                    pin.edge.value,
                    1 if pin.enabled else 0,
                ),
            )

    def delete_pin(self, pin_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM pins WHERE id = ?", (pin_id,))

    def get_pin(self, pin_id: str) -> Optional[Pin]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM pins WHERE id = ?", (pin_id,)).fetchone()
            return self._row_to_pin(row) if row else None

    def list_pins(self) -> List[Pin]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM pins ORDER BY bcm").fetchall()
            return [self._row_to_pin(r) for r in rows]

    def _row_to_pin(self, row: sqlite3.Row) -> Pin:
        return Pin(
            id=row["id"],
            bcm=int(row["bcm"]),
            name=row["name"],
            direction=PinDirection(row["direction"]),
            pull=row["pull"],
            active_low=bool(row["active_low"]),
            debounce_ms=int(row["debounce_ms"]),
            edge=PinEdge.from_str(row["edge"]),
            enabled=bool(row["enabled"]),
        )

    # ---- triggers ----

    def upsert_trigger(self, trigger: Trigger) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO triggers(id, pin_id, job_id, edge, enabled, name)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    pin_id=excluded.pin_id,
                    job_id=excluded.job_id,
                    edge=excluded.edge,
                    enabled=excluded.enabled,
                    name=excluded.name
                """,
                (
                    trigger.id,
                    trigger.pin_id,
                    trigger.job_id,
                    trigger.edge.value,
                    1 if trigger.enabled else 0,
                    trigger.name,
                ),
            )

    def delete_trigger(self, trigger_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))

    def get_trigger(self, trigger_id: str) -> Optional[Trigger]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
            return self._row_to_trigger(row) if row else None

    def list_triggers(self) -> List[Trigger]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM triggers ORDER BY id").fetchall()
            return [self._row_to_trigger(r) for r in rows]

    def list_triggers_for_pin(self, pin_id: str) -> List[Trigger]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM triggers WHERE pin_id = ?", (pin_id,)).fetchall()
            return [self._row_to_trigger(r) for r in rows]

    def _row_to_trigger(self, row: sqlite3.Row) -> Trigger:
        return Trigger(
            id=row["id"],
            pin_id=row["pin_id"],
            job_id=row["job_id"],
            edge=PinEdge.from_str(row["edge"]),
            enabled=bool(row["enabled"]),
            name=row["name"],
        )

    # ---- references + bboxes ----

    def upsert_reference(self, ref: ReferenceImage) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    """
                    INSERT INTO references(id, name, camera_id, image_path, width, height, created_at, notes)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        camera_id=excluded.camera_id,
                        image_path=excluded.image_path,
                        width=excluded.width,
                        height=excluded.height,
                        notes=excluded.notes
                    """,
                    (
                        ref.id,
                        ref.name,
                        ref.camera_id,
                        ref.image_path,
                        ref.width,
                        ref.height,
                        ref.created_at,
                        ref.notes,
                    ),
                )
                conn.execute("DELETE FROM bboxes WHERE reference_id = ?", (ref.id,))
                for b in ref.bboxes:
                    conn.execute(
                        """
                        INSERT INTO bboxes(id, reference_id, x, y, w, h, label, weight)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (b.id, ref.id, b.x, b.y, b.w, b.h, b.label, b.weight),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def delete_reference(self, ref_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM references WHERE id = ?", (ref_id,))

    def get_reference(self, ref_id: str) -> Optional[ReferenceImage]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM references WHERE id = ?", (ref_id,)).fetchone()
            if not row:
                return None
            bbox_rows = conn.execute(
                "SELECT * FROM bboxes WHERE reference_id = ? ORDER BY id", (ref_id,)
            ).fetchall()
            bboxes = [
                BoundingBox(
                    id=r["id"],
                    x=int(r["x"]),
                    y=int(r["y"]),
                    w=int(r["w"]),
                    h=int(r["h"]),
                    label=r["label"] or "",
                    weight=float(r["weight"]),
                )
                for r in bbox_rows
            ]
            return ReferenceImage(
                id=row["id"],
                name=row["name"],
                camera_id=row["camera_id"],
                image_path=row["image_path"],
                width=int(row["width"]),
                height=int(row["height"]),
                created_at=row["created_at"],
                notes=row["notes"] or "",
                bboxes=bboxes,
            )

    def list_references(self) -> List[ReferenceImage]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id FROM references ORDER BY created_at DESC, id").fetchall()
            return [self.get_reference(r["id"]) for r in rows if self.get_reference(r["id"])]

    # ---- jobs ----

    def upsert_job(self, job: Job) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    id, name, reference_id, camera_id, threshold, threshold_step, enabled,
                    actions_on_fail, actions_on_pass, notes, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    reference_id=excluded.reference_id,
                    camera_id=excluded.camera_id,
                    threshold=excluded.threshold,
                    threshold_step=excluded.threshold_step,
                    enabled=excluded.enabled,
                    actions_on_fail=excluded.actions_on_fail,
                    actions_on_pass=excluded.actions_on_pass,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    job.id,
                    job.name,
                    job.reference_id,
                    job.camera_id,
                    job.threshold,
                    job.threshold_step,
                    1 if job.enabled else 0,
                    json.dumps([a.to_dict() for a in job.actions_on_fail]),
                    json.dumps([a.to_dict() for a in job.actions_on_pass]),
                    job.notes,
                    job.created_at,
                    job.updated_at,
                ),
            )

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def list_jobs(self) -> List[Job]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY name").fetchall()
            return [self._row_to_job(r) for r in rows]

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        from ..models import action_from_dict  # local to keep top import light

        return Job(
            id=row["id"],
            name=row["name"],
            reference_id=row["reference_id"],
            camera_id=row["camera_id"],
            threshold=float(row["threshold"]),
            threshold_step=float(row["threshold_step"]),
            enabled=bool(row["enabled"]),
            actions_on_fail=[action_from_dict(d) for d in json.loads(row["actions_on_fail"] or "[]")],
            actions_on_pass=[action_from_dict(d) for d in json.loads(row["actions_on_pass"] or "[]")],
            notes=row["notes"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ---- inspections ----

    def record_inspection(self, ins: InspectionResult) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO inspections(
                    id, job_id, trigger_id, captured_at, score_overall, threshold, passed,
                    per_box, image_path, match_method, notes
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ins.id,
                    ins.job_id,
                    ins.trigger_id,
                    ins.captured_at,
                    ins.score_overall,
                    ins.threshold,
                    1 if ins.passed else 0,
                    json.dumps([b.to_dict() for b in ins.per_box]),
                    ins.image_path,
                    ins.match_method,
                    ins.notes,
                ),
            )

    def list_inspections(self, job_id: Optional[str] = None, limit: int = 200) -> List[InspectionResult]:
        with self._lock, self._connect() as conn:
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM inspections WHERE job_id = ? ORDER BY captured_at DESC LIMIT ?",
                    (job_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM inspections ORDER BY captured_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_inspection(r) for r in rows]

    def _row_to_inspection(self, row: sqlite3.Row) -> InspectionResult:
        from ..models import BBoxScore

        return InspectionResult(
            id=row["id"],
            job_id=row["job_id"],
            trigger_id=row["trigger_id"],
            captured_at=row["captured_at"],
            score_overall=float(row["score_overall"]),
            threshold=float(row["threshold"]),
            passed=bool(row["passed"]),
            per_box=[BBoxScore.from_dict(b) for b in json.loads(row["per_box"] or "[]")],
            image_path=row["image_path"],
            match_method=row["match_method"] or "TM_CCOEFF_NORMED",
            notes=row["notes"] or "",
        )

    # ---- alerts ----

    def create_alert(self, alert: AlertRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts(
                    id, inspection_id, job_id, raised_at, verdict, dismissed_at,
                    notes, image_path, score, threshold
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    alert.id,
                    alert.inspection_id,
                    alert.job_id,
                    alert.raised_at,
                    alert.verdict.value,
                    alert.dismissed_at,
                    alert.notes,
                    alert.image_path,
                    alert.score,
                    alert.threshold,
                ),
            )

    def dismiss_alert(
        self,
        alert_id: str,
        verdict: AlertVerdict,
        dismissed_at: str,
        notes: str = "",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET verdict = ?, dismissed_at = ?, notes = ?
                WHERE id = ?
                """,
                (verdict.value, dismissed_at, notes, alert_id),
            )

    def get_alert(self, alert_id: str) -> Optional[AlertRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._row_to_alert(row) if row else None

    def list_alerts(
        self,
        verdict: Optional[AlertVerdict] = None,
        job_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AlertRecord]:
        with self._lock, self._connect() as conn:
            sql = "SELECT * FROM alerts WHERE 1=1"
            params: list[Any] = []
            if verdict is not None:
                sql += " AND verdict = ?"
                params.append(verdict.value)
            if job_id is not None:
                sql += " AND job_id = ?"
                params.append(job_id)
            sql += " ORDER BY raised_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_alert(r) for r in rows]

    def _row_to_alert(self, row: sqlite3.Row) -> AlertRecord:
        return AlertRecord(
            id=row["id"],
            inspection_id=row["inspection_id"],
            job_id=row["job_id"],
            raised_at=row["raised_at"],
            verdict=AlertVerdict.from_str(row["verdict"]),
            dismissed_at=row["dismissed_at"],
            notes=row["notes"] or "",
            image_path=row["image_path"],
            score=float(row["score"]),
            threshold=float(row["threshold"]),
        )

    # ---- settings ----

    def get_settings(self) -> Settings:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id = 'singleton'").fetchone()
            if not row:
                s = Settings()
                self.save_settings(s)
                return s
            return self._row_to_settings(row)

    def save_settings(self, s: Settings) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(
                    id, default_threshold, default_threshold_step, min_threshold, max_threshold,
                    retention_days, history_retention_days, theme, auto_dismiss_after_hours
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    default_threshold=excluded.default_threshold,
                    default_threshold_step=excluded.default_threshold_step,
                    min_threshold=excluded.min_threshold,
                    max_threshold=excluded.max_threshold,
                    retention_days=excluded.retention_days,
                    history_retention_days=excluded.history_retention_days,
                    theme=excluded.theme,
                    auto_dismiss_after_hours=excluded.auto_dismiss_after_hours
                """,
                (
                    s.id,
                    s.default_threshold,
                    s.default_threshold_step,
                    s.min_threshold,
                    s.max_threshold,
                    s.retention_days,
                    s.history_retention_days,
                    s.theme,
                    s.auto_dismiss_after_hours,
                ),
            )

    def _row_to_settings(self, row: sqlite3.Row) -> Settings:
        return Settings(
            id=row["id"],
            default_threshold=float(row["default_threshold"]),
            default_threshold_step=float(row["default_threshold_step"]),
            min_threshold=float(row["min_threshold"]),
            max_threshold=float(row["max_threshold"]),
            retention_days=int(row["retention_days"]),
            history_retention_days=int(row["history_retention_days"]),
            theme=row["theme"],
            auto_dismiss_after_hours=int(row["auto_dismiss_after_hours"]),
        )

    # ---- threshold history ----

    def record_threshold_change(
        self,
        job_id: str,
        old_value: float,
        new_value: float,
        reason: str,
        alert_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO threshold_history(
                    job_id, old_value, new_value, reason, alert_id, created_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                (job_id, old_value, new_value, reason, alert_id, created_at),
            )

    def list_threshold_history(
        self, job_id: Optional[str] = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM threshold_history WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                    (job_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM threshold_history ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ---- seeding from config ----

    def seed_pins_from_config(self, pins: Iterable[Dict[str, Any]]) -> None:
        """Insert / update pins from a list of config dicts (idempotent)."""
        for p in pins or []:
            self.upsert_pin(Pin.from_dict(p))

    def close(self) -> None:
        """No persistent connection to close; reserved for future use."""
        return None


__all__ = ["StateStore", "SCHEMA_VERSION"]
