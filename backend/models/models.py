"""SQLAlchemy ORM models for the Elite Dangerous Power Play Analyzer.

Data is sourced from the Spansh populated systems dump (systems_populated.json.gz)
which contains one entry per system that is currently under a Power's influence.
Each sync run inserts a fresh snapshot row so historical trends accumulate.

PP 2.0 states stored in pp_system_snapshots.power_state:
  Stronghold | Fortified | Exploited | Turmoil | Undermined |
  Contested  | Expansion | InPrepareRadius | Prepared | HomeSystem
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from db.session import Base


# ---------------------------------------------------------------------------
# ingestion_runs — audit log for each sync job
# ---------------------------------------------------------------------------


class IngestionRun(Base):
    """Audit log entry for each Spansh Power Play ingestion job."""

    __tablename__ = "ingestion_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(32), nullable=False)          # "spansh_pp"
    started_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="running")  # running|completed|failed
    records_processed = Column(Integer, nullable=False, default=0)

    snapshots = relationship("PPSystemSnapshot", back_populates="ingestion_run")


# ---------------------------------------------------------------------------
# pp_systems — one row per unique star system (upserted each ingest)
# ---------------------------------------------------------------------------


class PPSystem(Base):
    """A star system that is (or has been) under a Power's influence."""

    __tablename__ = "pp_systems"

    id = Column(Integer, primary_key=True, index=True)
    system_id64 = Column(BigInteger, unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)
    allegiance = Column(String(128), nullable=True)
    population = Column(BigInteger, nullable=True)

    snapshots = relationship("PPSystemSnapshot", back_populates="system")


# ---------------------------------------------------------------------------
# pp_system_snapshots — insert-only time-series per system per ingest run
# ---------------------------------------------------------------------------


class PPSystemSnapshot(Base):
    """
    A point-in-time snapshot of a system's Power Play state.

    One row is inserted per system per ingestion run — never updated.
    This gives us the full history needed for trend analysis.

    spansh_updated_at — the timestamp Spansh reports for when the game servers
    last updated this system's PP data.  This is the authoritative data age field.
    snapshot_time is when WE ingested it; spansh_updated_at is when the GAME last
    changed it.  Queries should filter spansh_updated_at > NOW()-24h to exclude
    stale data that Spansh hasn't refreshed yet (e.g. systems where the PP state
    changed in-game but EDDN/Spansh hasn't received a new journal entry).
    """

    __tablename__ = "pp_system_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    system_id = Column(Integer, ForeignKey("pp_systems.id"), nullable=False, index=True)
    ingestion_run_id = Column(Integer, ForeignKey("ingestion_runs.id"), nullable=False, index=True)
    snapshot_time = Column(DateTime, default=func.now(), nullable=False, index=True)

    # When Spansh last received a game-data update for this system.
    # Sourced from the "updated_at" field in the Spansh search API response.
    # NULL for rows ingested before this column was added.
    spansh_updated_at = Column(DateTime, nullable=True, index=True)

    # Power Play fields from Spansh dump
    power = Column(String(128), nullable=True, index=True)   # controlling power (single)
    power_state = Column(String(64), nullable=True)           # Exploited|Fortified|Stronghold|Unoccupied
    # Reinforcement and undermining progress (raw commodity counts from Spansh)
    reinforcement = Column(Integer, nullable=True)
    undermining = Column(Integer, nullable=True)
    # 0.0–1.0 control progress toward next state
    control_progress = Column(Float, nullable=True)
    # For Unoccupied/contested systems: comma-separated list of all powers present
    # e.g. "A. Lavigny-Duval,Aisling Duval,Denton Patreus"
    powers_list = Column(String(512), nullable=True)
    # JSON array of {power, progress} dicts from power_conflict_progress field
    # e.g. '[{"power":"A. Lavigny-Duval","progress":1.46},...]'
    conflict_progress = Column(String(2048), nullable=True)

    system = relationship("PPSystem", back_populates="snapshots")
    ingestion_run = relationship("IngestionRun", back_populates="snapshots")


# ---------------------------------------------------------------------------
# admin_settings — scoring weight key/value store
# ---------------------------------------------------------------------------


class AdminSetting(Base):
    """Key/value store for scoring weights and app configuration."""

    __tablename__ = "admin_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), unique=True, index=True, nullable=False)
    value = Column(String(512), nullable=False)


# ---------------------------------------------------------------------------
# admin_users
# ---------------------------------------------------------------------------


class AdminUser(Base):
    """Admin accounts for the JWT-gated admin panel."""

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
