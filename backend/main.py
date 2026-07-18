"""Elite Dangerous Power Play Analyzer — FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# Import engine + Base, and all models so their tables are registered on Base.metadata.
from db.session import Base, engine  # noqa: E402
import models.models  # noqa: F401

# Create all tables that don't yet exist (idempotent on every startup).
Base.metadata.create_all(bind=engine)

from routers import auth, factions, systems, admin  # noqa: E402
from routers.admin import run_spansh_ingest_task, run_edsm_sync_task  # noqa: E402

logger = logging.getLogger(__name__)

# How often to re-run the Spansh bulk ingest (in hours).
SPANSH_INGEST_INTERVAL_HOURS: int = int(os.getenv("SPANSH_INGEST_INTERVAL_HOURS", "24"))
# How often to run the EDSM Power Play sync (in hours).
EDSM_SYNC_INTERVAL_HOURS: int = int(os.getenv("EDSM_SYNC_INTERVAL_HOURS", "6"))


# ---------------------------------------------------------------------------
# Lifespan — APScheduler startup/shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_spansh_ingest_task,
        trigger="interval",
        hours=SPANSH_INGEST_INTERVAL_HOURS,
        id="spansh_ingest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_edsm_sync_task,
        trigger="interval",
        hours=EDSM_SYNC_INTERVAL_HOURS,
        id="edsm_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    # Store on app.state so the admin /status endpoint can read next-run times.
    app.state.scheduler = scheduler
    logger.info(
        "Elite Powerplay API starting up. "
        "Spansh ingest scheduled every %d hour(s), "
        "EDSM sync scheduled every %d hour(s).",
        SPANSH_INGEST_INTERVAL_HOURS,
        EDSM_SYNC_INTERVAL_HOURS,
    )
    yield
    scheduler.shutdown(wait=False)
    app.state.scheduler = None
    logger.info("Elite Powerplay API shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Elite Dangerous Power Play Analyzer API",
    description="Backend for the Elite Dangerous Power Play Analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow all origins during development; tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(factions.router, prefix=API_PREFIX)
app.include_router(systems.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Basic liveness probe."""
    return {"status": "ok"}
