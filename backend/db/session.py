"""Database engine, session factory, declarative base, and FastAPI dependency.

TWO engines are configured:
  • `engine`            — used by every FastAPI request handler (via get_db)
  • `ingest_engine`     — used by the APScheduler's Spansh ingest task

The split prevents a long-running ingest (5–10 min, single connection held
for the whole run) from starving web traffic of connections.  Without this
split, a request burst plus the scheduled ingest could exhaust the 15-conn
default pool and cause `QueuePool limit of size 5 overflow 10 reached`.

Both engines share the same `DATABASE_URL` but have independent pool
configuration tuned to their workload:

    engine          — bursty web traffic (10 + 20 = 30, fail-fast 10s)
    ingest_engine   — predictable, long-running (2 + 0 = 2, generous 60s)

All pool knobs are environment-driven so they can be tuned at runtime with
`kubectl set env deploy/backend DB_POOL_SIZE=...` without a rebuild.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ──────────────────────────────────────────────────────────────────────────────
# Connection URL
# ──────────────────────────────────────────────────────────────────────────────

# PostgreSQL connection URL from environment; no SQLite fallback in this app.
# Rewrite postgresql:// → postgresql+psycopg:// so SQLAlchemy uses the psycopg3
# driver (psycopg[binary]) which supports Python 3.12+.
_raw_url: str = os.getenv(
    "DATABASE_URL",
    "postgresql://pp_user:pp_password@localhost:5432/elite_powerplay",
)
DATABASE_URL = _raw_url.replace(
    "postgresql://", "postgresql+psycopg://", 1
).replace(
    "postgresql+psycopg2://", "postgresql+psycopg://", 1
)


# ──────────────────────────────────────────────────────────────────────────────
# Pool config — read from env, with the values recommended in our runbook
# ──────────────────────────────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    """Parse an env var as int, falling back to `default` if unset/blank/invalid."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Parse an env var as bool ('true'/'false'/'1'/'0'/'yes'/'no')."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


# Web-request pool  ──────────────────────────────────────────────────────────
# Sized for bursty short-lived requests (FastAPI handlers, scoring reads,
# target analysis).  With replicas=1 and these defaults the backend can
# handle ~30 concurrent DB-using requests before failing fast.
WEB_POOL_SIZE       = _env_int("DB_POOL_SIZE",       10)
WEB_MAX_OVERFLOW    = _env_int("DB_MAX_OVERFLOW",    20)
WEB_POOL_TIMEOUT    = _env_int("DB_POOL_TIMEOUT",    10)
WEB_POOL_RECYCLE    = _env_int("DB_POOL_RECYCLE",  1800)
WEB_POOL_PRE_PING   = _env_bool("DB_POOL_PRE_PING", True)

# Ingest pool  ───────────────────────────────────────────────────────────────
# Sized for ONE serial long-running task (Spansh ingest).  No overflow — the
# scheduler is predictable.  A larger timeout because ingest is multi-minute.
INGEST_POOL_SIZE    = _env_int("DB_INGEST_POOL_SIZE",    2)
INGEST_MAX_OVERFLOW = _env_int("DB_INGEST_MAX_OVERFLOW", 0)
INGEST_POOL_TIMEOUT = _env_int("DB_INGEST_POOL_TIMEOUT", 60)
INGEST_POOL_RECYCLE = _env_int("DB_INGEST_POOL_RECYCLE", 1800)
INGEST_POOL_PRE_PING = _env_bool("DB_INGEST_POOL_PRE_PING", True)


def _build_engine(
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
    pool_recycle: int,
    pool_pre_ping: bool,
    label: str,
) -> Engine:
    """Construct a SQLAlchemy Engine with the given pool config.

    `pool_pre_ping=True` issues a cheap `SELECT 1` before each checkout from
    a pooled connection.  This catches connections killed by Postgres
    restarts, network blips, or `idle_in_transaction_session_timeout`
    without surfacing a 500 to the user.  ~0.1 ms cost in the happy path.

    `pool_recycle=1800` forces a fresh connection every 30 min, well under
    any reasonable Postgres-side `idle_session_timeout` (typically 8h+).
    This prevents "stale-but-not-dead" connections from accumulating in
    the pool.
    """
    return create_engine(
        DATABASE_URL,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        # Echo the SQL on every query when LOG_LEVEL=DEBUG.
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    )


engine: Engine = _build_engine(
    pool_size=WEB_POOL_SIZE,
    max_overflow=WEB_MAX_OVERFLOW,
    pool_timeout=WEB_POOL_TIMEOUT,
    pool_recycle=WEB_POOL_RECYCLE,
    pool_pre_ping=WEB_POOL_PRE_PING,
    label="web",
)

# Dedicated engine for the long-running Spansh ingest.  Kept separate so a
# 10-minute ingest cannot starve the web request pool.
ingest_engine: Engine = _build_engine(
    pool_size=INGEST_POOL_SIZE,
    max_overflow=INGEST_MAX_OVERFLOW,
    pool_timeout=INGEST_POOL_TIMEOUT,
    pool_recycle=INGEST_POOL_RECYCLE,
    pool_pre_ping=INGEST_POOL_PRE_PING,
    label="ingest",
)


# ──────────────────────────────────────────────────────────────────────────────
# Session factories
# ──────────────────────────────────────────────────────────────────────────────

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
IngestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ingest_engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ──────────────────────────────────────────────────────────────────────────────


def get_db():
    """FastAPI dependency that yields a database session and closes it on exit.

    Uses the `web` engine.  Ingest code MUST NOT use this — it has its own
    factory `IngestSessionLocal` backed by the dedicated `ingest_engine`.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
