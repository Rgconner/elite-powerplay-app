"""Admin router — ingest triggers and health probe (JWT-gated)."""

import logging

from fastapi import APIRouter, BackgroundTasks

from db.session import SessionLocal
from routers.deps import AdminUserDep
from services.ingestion import run_spansh_ingest

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
async def admin_health(admin: AdminUserDep) -> dict:
    """Liveness probe for the admin router (requires valid admin JWT)."""
    return {"status": "ok", "router": "admin", "admin_email": admin["email"]}


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
