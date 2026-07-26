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
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
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
    source = Column(String(32), nullable=False)          # "spansh_pp" | "edsm"
    started_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="running")  # running|completed|failed
    records_processed = Column(Integer, nullable=False, default=0)

    # ── Telemetry fields (added via ALTER TABLE at startup) ───────────────────
    duration_seconds = Column(Float, nullable=True)
    error_count = Column(Integer, nullable=False, default=0)
    api_calls_made = Column(Integer, nullable=False, default=0)
    api_errors = Column(Integer, nullable=False, default=0)
    error_detail = Column(String(2048), nullable=True)
    bytes_downloaded = Column(BigInteger, nullable=False, default=0)  # raw bytes from source API
    pages_fetched = Column(Integer, nullable=False, default=0)        # paginated pages retrieved

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

    # ── Merit decay (PP2.0 mechanic) ────────────────────────────────────────
    # Estimated CP merit decay computed once per cycle per system.
    # Only computed for Stronghold/Fortified/Exploited states.
    cp_decay = Column(Integer, nullable=True)
    # The cycle start (Thursday 07:00 UTC) this cp_decay was computed for.
    decay_cycle_start = Column(DateTime, nullable=True, index=True)

    system = relationship("PPSystem", back_populates="snapshots")
    ingestion_run = relationship("IngestionRun", back_populates="snapshots")


# ---------------------------------------------------------------------------
# spansh_enrichment — cached PLAT/BOOM data per system (12-hour TTL)
# ---------------------------------------------------------------------------


class SpanshEnrichment(Base):
    """
    Cached Spansh body/minor-faction enrichment data for a system.

    has_platinum — true if any planet body in the system has a Platinum signal.
    has_boom     — true if any minor faction in the system has BOOM as an active state.
    has_pristine — true if any body in the system has a "Pristine" reserve level.
    cached_at    — when this row was last fetched (first-access cache).
    """

    __tablename__ = "spansh_enrichment"

    system_id64 = Column(BigInteger, primary_key=True, index=True, nullable=False)
    has_platinum = Column(Boolean, nullable=False, default=False)
    has_boom = Column(Boolean, nullable=False, default=False)
    has_pristine = Column(Boolean, nullable=False, default=False)
    cached_at = Column(DateTime, default=func.now(), nullable=False)


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


# ---------------------------------------------------------------------------
# pp_powerplay_events — raw EDDN PowerplayMerits events (insert-only)
# ---------------------------------------------------------------------------


class PpPowerplayEvent(Base):
    """
    Raw PowerplayMerits events received from the EDDN ZeroMQ stream.

    Each row represents a single player merit-earning event.  Insert-only —
    never updated.  Deduplicated by message_id (EDDN header.messageID).

    The EDDN journal/1 schema forwards all journal events; we filter on
    event == "PowerplayMerits" in the listener service.

    Fields from the ED journal event:
      Power       — power name (e.g. "A. Lavigny-Duval")
      System      — system name
      Merits      — raw merits earned (always positive)
      StarSystem  — system name (EDDN-required field)
      SystemAddress — system id64 (EDDN-required field)
      StarPos     — [x, y, z] coordinates (EDDN-required field)
    """

    __tablename__ = "pp_powerplay_events"

    id = Column(BigInteger, primary_key=True, index=True)
    message_id = Column(String(64), unique=True, nullable=False, index=True)
    uploader_id = Column(String(64), nullable=True)
    event_timestamp = Column(DateTime, nullable=False, index=True)
    gateway_ts = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, default=func.now(), nullable=False)
    schema_ref = Column(String(128), nullable=True)
    power = Column(String(128), nullable=False, index=True)
    system_name = Column(String(255), nullable=False, index=True)
    system_id64 = Column(BigInteger, nullable=True, index=True)
    merits = Column(Integer, nullable=False)
    star_pos_x = Column(Float, nullable=True)
    star_pos_y = Column(Float, nullable=True)
    star_pos_z = Column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint("merits > 0", name="ck_ppe_merits_positive"),
    )


# ---------------------------------------------------------------------------
# pp_realtime_state — accumulated real-time CP deltas (UPSERTed every 60s)
# ---------------------------------------------------------------------------


class PpRealtimeState(Base):
    """
    Accumulated real-time control point deltas per (power, system).

    Updated every 60 seconds by the realtime_accumulator service.
    Stores the sum of EDDN merits received since the last Spansh snapshot
    boundary, converted to CPs at a 4:1 ratio.

    Orientation logic (simplified):
      - If event_power == controlling_power → CPs add to reinforcement
      - If event_power != controlling_power → CPs add to undermining
      - If no controlling_power → CPs add to reinforcement (all powers)
    """

    __tablename__ = "pp_realtime_state"

    power = Column(String(128), primary_key=True)
    system_id64 = Column(BigInteger, primary_key=True)
    controlling_power = Column(String(128), nullable=True)
    state_at_boundary = Column(String(32), nullable=True)
    boundary_ts = Column(DateTime, nullable=False)
    merits_since_ts = Column(Integer, nullable=False, default=0)
    cp_since_ts = Column(Numeric(12, 2), nullable=False, default=0)
    cp_as_reinforcement = Column(Numeric(12, 2), nullable=False, default=0)
    cp_as_undermining = Column(Numeric(12, 2), nullable=False, default=0)
    latest_event_ts = Column(DateTime, nullable=True)
    refreshed_at = Column(DateTime, default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# eddn_feed_stats — singleton heartbeat written by the EDDN listener process
# ---------------------------------------------------------------------------


class EddnFeedStats(Base):
    """Persistent heartbeat written by the eddn-listener every STATS_LOG_INTERVAL_SECONDS.

    The listener upserts a single row (id=1) so the backend can query
    the latest stream health without parsing log files.
    """

    __tablename__ = "eddn_feed_stats"

    id = Column(Integer, primary_key=True)           # always 1 (singleton)
    recorded_at = Column(DateTime, nullable=False)    # when this row was last written
    listener_started_at = Column(DateTime, nullable=False)
    events_total = Column(BigInteger, nullable=False, default=0)   # since process start
    events_last_5min = Column(Integer, nullable=False, default=0)  # since last flush
    dedup_rejected = Column(Integer, nullable=False, default=0)    # ON CONFLICT skips
    decode_errors = Column(Integer, nullable=False, default=0)
    last_event_ts = Column(DateTime, nullable=True)                # most recent event_timestamp


# ---------------------------------------------------------------------------
# enrichment_stats — daily cache hit/miss counters for Spansh enrichment
# ---------------------------------------------------------------------------


class EnrichmentStats(Base):
    """One row per calendar day tracking Spansh enrichment cache performance."""

    __tablename__ = "enrichment_stats"

    stat_date = Column(DateTime, primary_key=True)   # truncated to day (UTC)
    cache_hits = Column(Integer, nullable=False, default=0)
    cache_misses = Column(Integer, nullable=False, default=0)
    api_calls = Column(Integer, nullable=False, default=0)
    api_errors = Column(Integer, nullable=False, default=0)
    total_fetch_ms = Column(Float, nullable=False, default=0.0)   # for avg calc
    bytes_fetched = Column(BigInteger, nullable=False, default=0) # raw response bytes from Spansh


# ---------------------------------------------------------------------------
# audit_log — admin action audit trail
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Records every admin settings change and ingest trigger for auditability."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    admin_email = Column(String(255), nullable=False, index=True)
    # Human-readable action name, e.g. "setting_update" or "ingest_spansh"
    action = Column(String(64), nullable=False)
    # The key/resource being affected (setting key or ingest type); nullable for
    # actions that have no single resource (e.g. bulk actions)
    resource_key = Column(String(255), nullable=True)
    old_value = Column(String(512), nullable=True)
    new_value = Column(String(512), nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
