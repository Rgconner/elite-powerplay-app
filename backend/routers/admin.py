"""Admin router — ingest triggers, status, settings, and account management (JWT-gated)."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from db.session import IngestSessionLocal
from models.models import AdminSetting, AdminUser, AuditLog, IngestionRun
from models.schemas import AdminSettingSchema, IngestionRunSchema
from routers.auth import hash_password, verify_password
from routers.deps import AdminUserDep, get_db
from services.ingestion import run_spansh_ingest
from version import BACKEND_VERSION, BACKEND_RELEASE_DATE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process background job status store
# Keyed by UUID string; values: {status, error, started_at}
# ---------------------------------------------------------------------------

BACKGROUND_JOBS: dict[str, dict] = {}


def _cleanup_old_jobs() -> None:
    """Remove job entries older than 24 hours from BACKGROUND_JOBS."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    stale = [jid for jid, info in BACKGROUND_JOBS.items() if info["started_at"] < cutoff]
    for jid in stale:
        del BACKGROUND_JOBS[jid]


router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Public endpoints — no auth required
# ---------------------------------------------------------------------------


@router.get("/version", include_in_schema=True)
def get_version() -> dict:
    """Return backend version and release date — public, no JWT needed."""
    return {
        "backend_version": BACKEND_VERSION,
        "backend_release_date": BACKEND_RELEASE_DATE,
    }


@router.get("/ingest-status", include_in_schema=True)
def get_ingest_status(request: Request, db: Session = Depends(get_db)) -> dict:
    """Return last ingest run info and next scheduled run time — public, no JWT needed."""
    last_run = (
        db.query(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .first()
    )

    spansh_next: str | None = None
    try:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler:
            job = scheduler.get_job("spansh_ingest")
            if job and job.next_run_time:
                spansh_next = job.next_run_time.isoformat()
    except Exception:
        pass

    if last_run is None:
        return {
            "last_run_at": None,
            "status": None,
            "records_processed": None,
            "next_run_at": spansh_next,
        }

    return {
        "last_run_at": last_run.started_at.isoformat() if last_run.started_at else None,
        "completed_at": last_run.completed_at.isoformat() if last_run.completed_at else None,
        "status": last_run.status,
        "records_processed": last_run.records_processed,
        "next_run_at": spansh_next,
    }


def run_spansh_ingest_task(job_id: str | None = None) -> None:
    """Wrapper used by both BackgroundTasks and APScheduler.

    Uses the dedicated `IngestSessionLocal` (backed by `ingest_engine`) so
    the long-running Spansh ingest cannot starve the FastAPI request pool.
    The ingest holds a single connection for 5-10 minutes - a separate
    pool with pool_size=2, max_overflow=0 keeps web traffic insulated.

    When *job_id* is provided the job's status in BACKGROUND_JOBS is updated
    to reflect pending -> running -> completed / failed.
    """
    if job_id and job_id in BACKGROUND_JOBS:
        BACKGROUND_JOBS[job_id]["status"] = "running"
    db = IngestSessionLocal()
    try:
        run_spansh_ingest(db)
        if job_id and job_id in BACKGROUND_JOBS:
            BACKGROUND_JOBS[job_id]["status"] = "completed"
    except Exception as exc:
        logger.exception("Background Spansh PP ingest task failed")
        if job_id and job_id in BACKGROUND_JOBS:
            BACKGROUND_JOBS[job_id]["status"] = "failed"
            BACKGROUND_JOBS[job_id]["error"] = str(exc)
    finally:
        db.close()


@router.get("/health")
async def admin_health(admin: AdminUserDep) -> dict:
    return {"status": "ok", "router": "admin", "admin_email": admin["email"]}


@router.get("/status")
def get_status(request: Request, admin: AdminUserDep, db: Session = Depends(get_db)) -> dict:
    """Return the 10 most recent ingestion runs and scheduler next-run time."""
    spansh_next: str | None = None
    try:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler:
            job = scheduler.get_job("spansh_ingest")
            if job and job.next_run_time:
                spansh_next = job.next_run_time.isoformat()
    except Exception:
        pass

    runs = (
        db.query(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .limit(10)
        .all()
    )
    return {
        "recent_runs": [IngestionRunSchema.model_validate(r) for r in runs],
        "spansh_next_run": spansh_next,
    }


@router.get("/settings")
def get_settings(admin: AdminUserDep, db: Session = Depends(get_db)) -> list[AdminSettingSchema]:
    return db.query(AdminSetting).all()


class SettingUpdate(BaseModel):
    key: str
    value: str

    # Key-name conventions: *_weight / *_max / *_bonus → numeric scoring multipliers [0, 10000]
    #                       *_threshold                → day-count thresholds [0, 365]
    @field_validator("value", mode="before")
    @classmethod
    def validate_value_range(cls, v: str, info) -> str:
        key: str = (info.data or {}).get("key", "")
        if key.endswith(("_weight", "_max", "_bonus")):
            try:
                num = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"'{key}' must be a numeric value")
            if not (0 <= num <= 10000):
                raise ValueError(f"'{key}' must be between 0 and 10000, got {v}")
        elif key.endswith("_threshold"):
            try:
                num = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"'{key}' must be a numeric value")
            if not (0 <= num <= 365):
                raise ValueError(f"'{key}' must be between 0 and 365, got {v}")
        return v


@router.patch("/settings")
def update_settings(
    updates: list[SettingUpdate],
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> list[AdminSettingSchema]:
    for update in updates:
        existing = db.query(AdminSetting).filter(AdminSetting.key == update.key).first()
        old_value = existing.value if existing else None
        if existing:
            existing.value = update.value
        else:
            db.add(AdminSetting(key=update.key, value=update.value))
        db.add(AuditLog(
            admin_email=admin["email"],
            action="setting_update",
            resource_key=update.key,
            old_value=old_value,
            new_value=update.value,
        ))
    db.commit()
    return db.query(AdminSetting).all()


@router.post("/ingest/spansh")
async def trigger_spansh_ingest(
    background_tasks: BackgroundTasks,
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> dict:
    """Kick off a Spansh Power Play ingest in the background."""
    _cleanup_old_jobs()
    job_id = str(uuid4())
    BACKGROUND_JOBS[job_id] = {
        "status": "pending",
        "error": None,
        "started_at": datetime.now(tz=timezone.utc),
    }
    background_tasks.add_task(run_spansh_ingest_task, job_id)
    db.add(AuditLog(
        admin_email=admin["email"],
        action="ingest_spansh",
        resource_key="spansh",
    ))
    db.commit()
    logger.info("Spansh PP ingest triggered manually by %s", admin["email"])
    return {"message": "Spansh PP ingest started in background", "job_id": job_id}


@router.get("/ingest/status/{job_id}")
def get_ingest_job_status(job_id: str, admin: AdminUserDep) -> dict:
    """Return the status of a background ingest job by its job ID.

    Returns the job entry with status, error, and started_at, or raises 404 if
    the job ID is unknown or has already expired.
    """
    job = BACKGROUND_JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found or has expired.",
        )
    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job["error"],
        "started_at": job["started_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/audit")
def get_audit_log(
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return the 200 most recent audit log entries, newest first."""
    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id,
            "admin_email": r.admin_email,
            "action": r.action,
            "resource_key": r.resource_key,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters.")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: object) -> str:
        # `info.data` contains already-validated fields
        data = getattr(info, "data", {})
        if "new_password" in data and v != data["new_password"]:
            raise ValueError("Passwords do not match.")
        return v


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> dict:
    """Change the authenticated admin's password.

    Requires the current password for verification.  The new password is
    bcrypt-hashed before storage (same pipeline as the initial account
    creation in create_admin.py).
    """
    user = db.query(AdminUser).filter(AdminUser.id == admin["id"]).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found.")

    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    user.hashed_password = hash_password(body.new_password)
    db.commit()
    logger.info("Password changed for admin %s", user.email)
    return {"message": "Password changed successfully."}
