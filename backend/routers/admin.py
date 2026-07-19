"""Admin router — ingest triggers, status, settings, and account management (JWT-gated)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.models import AdminSetting, AdminUser, IngestionRun
from models.schemas import AdminSettingSchema, IngestionRunSchema
from routers.auth import hash_password, verify_password
from routers.deps import AdminUserDep, get_db
from services.ingestion import run_spansh_ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Public endpoint — no auth required
# ---------------------------------------------------------------------------


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


def run_spansh_ingest_task() -> None:
    """Wrapper used by both BackgroundTasks and APScheduler."""
    db = SessionLocal()
    try:
        run_spansh_ingest(db)
    except Exception:
        logger.exception("Background Spansh PP ingest task failed")
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


@router.patch("/settings")
def update_settings(
    updates: list[SettingUpdate],
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> list[AdminSettingSchema]:
    for update in updates:
        existing = db.query(AdminSetting).filter(AdminSetting.key == update.key).first()
        if existing:
            existing.value = update.value
        else:
            db.add(AdminSetting(key=update.key, value=update.value))
    db.commit()
    return db.query(AdminSetting).all()


@router.post("/ingest/spansh")
async def trigger_spansh_ingest(
    background_tasks: BackgroundTasks,
    admin: AdminUserDep,
) -> dict:
    """Kick off a Spansh Power Play ingest in the background."""
    background_tasks.add_task(run_spansh_ingest_task)
    logger.info("Spansh PP ingest triggered manually by %s", admin["email"])
    return {"message": "Spansh PP ingest started in background"}


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
