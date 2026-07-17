"""Admin router — ingest triggers, status, and settings (JWT-gated)."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.models import AdminSetting, IngestionRun
from models.schemas import AdminSettingSchema, IngestionRunSchema
from routers.deps import AdminUserDep, get_db
from services.ingestion import run_spansh_ingest
from services.edsm_sync import run_edsm_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Background task helpers
# Each helper creates its own DB session because BackgroundTasks execute after
# the HTTP response has been sent and the request-scoped session is closed.
# ---------------------------------------------------------------------------


def run_spansh_ingest_task() -> None:
    """Wrapper used by both BackgroundTasks and APScheduler."""
    db = SessionLocal()
    try:
        run_spansh_ingest(db)
    except Exception:
        logger.exception("Background Spansh ingest task failed")
    finally:
        db.close()


def run_edsm_sync_task() -> None:
    """Standalone helper — creates its own DB session, safe for BackgroundTasks and APScheduler."""
    db = SessionLocal()
    try:
        run_edsm_sync(db)
    except Exception:
        logger.exception("Background EDSM sync task failed")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
async def admin_health(admin: AdminUserDep) -> dict:
    """Liveness probe for the admin router (requires valid admin JWT)."""
    return {"status": "ok", "router": "admin", "admin_email": admin["email"]}


@router.get("/status")
def get_status(admin: AdminUserDep, db: Session = Depends(get_db)) -> dict:
    """Return the 10 most recent ingestion runs and scheduler next-run times."""
    # Import scheduler reference from main to get next run times (best-effort)
    spansh_next: str | None = None
    edsm_next: str | None = None
    try:
        from main import app  # noqa: PLC0415
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            spansh_job = scheduler.get_job("spansh_ingest")
            edsm_job = scheduler.get_job("edsm_sync")
            if spansh_job and spansh_job.next_run_time:
                spansh_next = spansh_job.next_run_time.isoformat()
            if edsm_job and edsm_job.next_run_time:
                edsm_next = edsm_job.next_run_time.isoformat()
    except Exception:
        pass  # scheduler not accessible — return None times

    runs = (
        db.query(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .limit(10)
        .all()
    )
    return {
        "recent_runs": [IngestionRunSchema.model_validate(r) for r in runs],
        "spansh_next_run": spansh_next,
        "edsm_next_run": edsm_next,
    }


@router.get("/settings")
def get_settings(admin: AdminUserDep, db: Session = Depends(get_db)) -> list[AdminSettingSchema]:
    """Return all admin settings as a list of {key, value} objects."""
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
    """Upsert a list of {key, value} setting pairs."""
    for update in updates:
        existing = db.query(AdminSetting).filter(AdminSetting.key == update.key).first()
        if existing:
            existing.value = update.value
        else:
            db.add(AdminSetting(key=update.key, value=update.value))
    db.commit()
    return db.query(AdminSetting).all()


@router.post("/ingest/edsm")
def trigger_edsm_sync(
    background_tasks: BackgroundTasks,
    admin: AdminUserDep,
) -> dict:
    """Kick off an EDSM Power Play sync in the background.

    Returns immediately; the sync runs asynchronously and updates the
    ingestion_runs row when complete.
    """
    background_tasks.add_task(run_edsm_sync_task)
    logger.info("EDSM sync triggered manually by %s", admin["email"])
    return {"message": "EDSM sync started in background"}


@router.post("/ingest/spansh")
async def trigger_spansh_ingest(
    background_tasks: BackgroundTasks,
    admin: AdminUserDep,
) -> dict:
    """Kick off a Spansh factions.json.gz ingest in the background.

    Returns immediately; the ingest runs asynchronously and updates the
    ingestion_runs row when complete.
    """
    background_tasks.add_task(run_spansh_ingest_task)
    logger.info("Spansh ingest triggered manually by %s", admin["email"])
    return {"message": "Spansh ingest started in background"}
