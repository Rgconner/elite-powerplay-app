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
    _conn.execute(_text(
        "ALTER TABLE pp_system_snapshots "
        "ADD COLUMN IF NOT EXISTS spansh_updated_at TIMESTAMP"
    ))

    # ── Merit decay columns (PP2.0 CP decay mechanic) ──────────────────────
    _conn.execute(_text(
        "ALTER TABLE pp_system_snapshots "
        "ADD COLUMN IF NOT EXISTS cp_decay INTEGER"
    ))
    _conn.execute(_text(
        "ALTER TABLE pp_system_snapshots "
        "ADD COLUMN IF NOT EXISTS decay_cycle_start TIMESTAMP"
    ))
    _conn.execute(_text(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_decay_cycle "
        "ON pp_system_snapshots (decay_cycle_start)"
    ))
    # Index for fast staleness filtering (WHERE spansh_updated_at > NOW()-24h)
    _conn.execute(_text(
        "CREATE INDEX IF NOT EXISTS ix_pp_system_snapshots_spansh_updated_at "
        "ON pp_system_snapshots (spansh_updated_at)"
    ))
    # spansh_enrichment table for cached PLAT/BOOM/PRISTINE data (first-access cache)
    _conn.execute(_text(
        "CREATE TABLE IF NOT EXISTS spansh_enrichment ("
        "  system_id64 BIGINT PRIMARY KEY,"
        "  has_platinum BOOLEAN NOT NULL DEFAULT FALSE,"
        "  has_boom BOOLEAN NOT NULL DEFAULT FALSE,"
        "  has_pristine BOOLEAN NOT NULL DEFAULT FALSE,"
        "  cached_at TIMESTAMP NOT NULL DEFAULT NOW()"
        ")"
    ))
    # Add has_pristine column for existing deployments
    _conn.execute(_text(
        "ALTER TABLE spansh_enrichment "
        "ADD COLUMN IF NOT EXISTS has_pristine BOOLEAN NOT NULL DEFAULT FALSE"
    ))

    # ── EDDN PowerplayMerits events table (insert-only, raw event store) ────
    _conn.execute(_text(
        "CREATE TABLE IF NOT EXISTS pp_powerplay_events ("
        "  id BIGSERIAL PRIMARY KEY,"
        "  message_id VARCHAR(64) NOT NULL,"
        "  uploader_id VARCHAR(64),"
        "  event_timestamp TIMESTAMP NOT NULL,"
        "  gateway_ts TIMESTAMP,"
        "  ingested_at TIMESTAMP NOT NULL DEFAULT NOW(),"
        "  schema_ref VARCHAR(128),"
        "  power VARCHAR(128) NOT NULL,"
        "  system_name VARCHAR(255) NOT NULL,"
        "  system_id64 BIGINT,"
        "  merits INTEGER NOT NULL,"
        "  star_pos_x FLOAT,"
        "  star_pos_y FLOAT,"
        "  star_pos_z FLOAT,"
        "  CONSTRAINT uq_ppe_message_id UNIQUE (message_id),"
        "  CONSTRAINT ck_ppe_merits_positive CHECK (merits > 0)"
        ")"
    ))
    _conn.execute(_text(
        "CREATE INDEX IF NOT EXISTS idx_ppe_power_sys "
        "ON pp_powerplay_events (power, system_id64)"
    ))
    _conn.execute(_text(
        "CREATE INDEX IF NOT EXISTS idx_ppe_timestamp "
        "ON pp_powerplay_events (event_timestamp)"
    ))
    _conn.execute(_text(
        "CREATE INDEX IF NOT EXISTS idx_ppe_system_name "
        "ON pp_powerplay_events (system_name)"
    ))

    # ── Real-time CP state table (UPSERTed every 60s by accumulator) ────────
    _conn.execute(_text(
        "CREATE TABLE IF NOT EXISTS pp_realtime_state ("
        "  power VARCHAR(128) NOT NULL,"
        "  system_id64 BIGINT NOT NULL,"
        "  controlling_power VARCHAR(128),"
        "  state_at_boundary VARCHAR(32),"
        "  boundary_ts TIMESTAMP NOT NULL,"
        "  merits_since_ts INTEGER NOT NULL DEFAULT 0,"
        "  cp_since_ts NUMERIC(12,2) NOT NULL DEFAULT 0,"
        "  cp_as_reinforcement NUMERIC(12,2) NOT NULL DEFAULT 0,"
        "  cp_as_undermining NUMERIC(12,2) NOT NULL DEFAULT 0,"
        "  latest_event_ts TIMESTAMP,"
        "  refreshed_at TIMESTAMP NOT NULL DEFAULT NOW(),"
        "  PRIMARY KEY (power, system_id64)"
        ")"
    ))
    _conn.commit()

from routers import auth, admin  # noqa: E402
from routers.powers import router as powers_router, systems_router  # noqa: E402
from routers.spansh import router as spansh_router  # noqa: E402
from routers.admin import run_spansh_ingest_task  # noqa: E402
from routers.architecture import router as architecture_router  # noqa: E402
from services.realtime_accumulator import run_realtime_accumulator  # noqa: E402

logger = logging.getLogger(__name__)

SPANSH_INGEST_INTERVAL_HOURS: int = int(os.getenv("SPANSH_INGEST_INTERVAL_HOURS", "24"))


def run_realtime_accumulator_task():
    """Wrapper for realtime accumulator that creates its own DB session."""
    from db.session import SessionLocal
    db = SessionLocal()
    try:
        run_realtime_accumulator(db)
    except Exception as e:
        logger.error("Realtime accumulator failed: %s", e)
    finally:
        db.close()


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
        run_realtime_accumulator_task,
        trigger="interval",
        seconds=60,
        id="realtime_accumulator",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Elite Powerplay API starting up. "
        "Spansh PP ingest scheduled every %d hour(s). "
        "Realtime accumulator scheduled every 60 seconds.",
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

app.include_router(auth.router,          prefix=API_PREFIX)
app.include_router(powers_router,        prefix=API_PREFIX)
app.include_router(systems_router,       prefix=API_PREFIX)
app.include_router(spansh_router,        prefix=API_PREFIX)
app.include_router(admin.router,         prefix=API_PREFIX)
app.include_router(architecture_router,  prefix=API_PREFIX)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok"}
