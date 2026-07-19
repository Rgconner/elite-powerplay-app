"""Elite Dangerous Power Play Analyzer — FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from version import BACKEND_VERSION

load_dotenv()

from db.session import Base, engine  # noqa: E402
import models.models  # noqa: F401
from sqlalchemy import text as _text  # noqa: E402

Base.metadata.create_all(bind=engine)

# ── Incremental schema migrations ────────────────────────────────────────────
# SQLAlchemy's create_all() only creates missing tables, not missing columns.
# We run explicit ADD COLUMN IF NOT EXISTS here so existing deployments pick up
# new fields without a full DB wipe.
with engine.connect() as _conn:
    _conn.execute(_text(
        "ALTER TABLE pp_system_snapshots "
        "ADD COLUMN IF NOT EXISTS powers_list VARCHAR(512)"
    ))
    _conn.execute(_text(
        "ALTER TABLE pp_system_snapshots "
        "ADD COLUMN IF NOT EXISTS conflict_progress VARCHAR(2048)"
    ))
    _conn.commit()

from routers import auth, admin  # noqa: E402
from routers.powers import router as powers_router, systems_router  # noqa: E402
from routers.admin import run_spansh_ingest_task  # noqa: E402

logger = logging.getLogger(__name__)

SPANSH_INGEST_INTERVAL_HOURS: int = int(os.getenv("SPANSH_INGEST_INTERVAL_HOURS", "24"))


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
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Elite Powerplay API starting up. "
        "Spansh PP ingest scheduled every %d hour(s).",
        SPANSH_INGEST_INTERVAL_HOURS,
    )
    yield
    scheduler.shutdown(wait=False)
    app.state.scheduler = None
    logger.info("Elite Powerplay API shutting down.")


app = FastAPI(
    title="Elite Dangerous Power Play Analyzer API",
    description="Backend for the Elite Dangerous Power Play Analyzer",
    version=BACKEND_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"

app.include_router(auth.router,     prefix=API_PREFIX)
app.include_router(powers_router,   prefix=API_PREFIX)
app.include_router(systems_router,  prefix=API_PREFIX)
app.include_router(admin.router,    prefix=API_PREFIX)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok"}
