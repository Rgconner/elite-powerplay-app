"""EDDN ZeroMQ Listener for live Power Play system state.

Subscribes to the EDDN relay (tcp://eddn.edcd.io:9500) and captures the
Powerplay fields that FSDJump / Location / CarrierJump journal events carry
(ControllingPower, PowerplayState, Reinforcement, Undermining, ...).  Each
observed state is written as a pp_system_snapshots row (ingestion_run_id NULL),
so every read path that takes the latest snapshot per system sees live data
between Spansh ingests.

EDDN does not relay PowerplayMerits (it is not among the journal/1 schema's
allowed events) and its headers carry no messageID -- the original design
built on both and inserted nothing.

Watchdog: EDDN normally delivers several messages per second.  If nothing
arrives for WATCHDOG_SILENCE_SECONDS the SUB socket is torn down and
reconnected (a half-open TCP connection never errors on its own).  The
liveness heartbeat file is only touched when a message is received, so if
reconnecting does not restore the feed the k8s probe restarts the pod.

Runs as an isolated k8s deployment, separate from the main backend.
"""

import hashlib
import json
import logging
import os
import sys
import time
import zlib
from datetime import datetime
from typing import Optional

import zmq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Copied in at image build time from backend/services/decay.py (see Dockerfile)
from decay import compute_cp_decay, current_cycle_start

# Configure logging - honor LOG_LEVEL env var
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("eddn-listener")

# Database connection
# Normalize the DB URL to use psycopg3 (psycopg[binary]) instead of psycopg2.
# The k8s secret may provide postgresql:// or postgresql+psycopg2://
_raw_url = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/powerplay")
DATABASE_URL = _raw_url.replace(
    "postgresql://", "postgresql+psycopg://", 1
).replace(
    "postgresql+psycopg2://", "postgresql+psycopg://", 1
)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    # Long-lived daemon over TCP to Postgres: bound the pool checkout wait and
    # the TCP connect so an unreachable DB cannot hang the listener forever.
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
    connect_args={"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))},
)
SessionLocal = sessionmaker(bind=engine)

# EDDN connection - env-configurable with defaults
EDDN_RELAY = os.getenv("EDDN_RELAY_URL", "tcp://eddn.edcd.io:9500")
EDDN_SCHEMA = os.getenv("EDDN_SCHEMA_URL", "https://eddn.edcd.io/schemas/journal/1")
TARGET_EVENT = os.getenv("TARGET_EVENT", "PowerplayMerits")
# Journal events whose message carries the system's Powerplay state
STATE_EVENTS = {"FSDJump", "Location", "CarrierJump"}

# Write an unchanged system state at most this often (popular systems are
# jumped into many times a minute); a changed state is always written.
SNAPSHOT_MIN_INTERVAL_SECONDS = int(os.getenv("SNAPSHOT_MIN_INTERVAL_SECONDS", "900"))
# Ignore journal events older than this (clients replaying old journals)
MAX_EVENT_AGE_SECONDS = int(os.getenv("MAX_EVENT_AGE_SECONDS", "3600"))

# Reconnect the SUB socket if the relay goes quiet for this long
WATCHDOG_SILENCE_SECONDS = int(os.getenv("WATCHDOG_SILENCE_SECONDS", "120"))
HEARTBEAT_FILE = "/tmp/eddn_heartbeat"

# Retry configuration
RETRY_DELAY_INITIAL = 1
RETRY_DELAY_MAX = 30

# Stats logging configuration
STATS_LOG_INTERVAL_SECONDS = 300  # Log stats every 5 minutes


def _hex_preview(data: bytes, max_bytes: int = 32) -> str:
    """Return a hex preview of bytes for diagnostic logging."""
    preview = data[:max_bytes]
    return preview.hex() + ("..." if len(data) > max_bytes else "")


def _decode_payload(raw_payload: bytes) -> Optional[str]:
    """Attempt zlib decompression, then fall back to raw UTF-8 decode.

    EDDN relays typically send zlib-compressed JSON. If decompression
    fails, fall back to treating the payload as raw UTF-8 so we can
    still log useful diagnostics.
    """
    # Try zlib decompression first (EDDN uses compressed payloads)
    try:
        decompressed = zlib.decompress(raw_payload)
        return decompressed.decode("utf-8")
    except zlib.error as e:
        logger.warning(
            "Zlib decompression failed (len=%d, hex=%s): %s",
            len(raw_payload),
            _hex_preview(raw_payload),
            e,
        )
    except UnicodeDecodeError as e:
        logger.warning(
            "UTF-8 decode failed after zlib decompression (len=%d, hex=%s): %s",
            len(raw_payload),
            _hex_preview(raw_payload),
            e,
        )

    # Fallback: try raw UTF-8 without decompression
    try:
        return raw_payload.decode("utf-8")
    except UnicodeDecodeError as e:
        logger.warning(
            "UTF-8 decode failed on raw payload (len=%d, hex=%s): %s",
            len(raw_payload),
            _hex_preview(raw_payload),
            e,
        )

    return None


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp from EDDN message."""
    try:
        # Handle various ISO formats
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str).replace(tzinfo=None)
    except Exception as e:
        logger.warning("Failed to parse timestamp '%s': %s", ts_str, e)
        return None


def resolve_system_id64(system_name: str, db_session) -> Optional[int]:
    """Look up system_id64 from pp_systems table by name."""
    try:
        result = db_session.execute(
            text("SELECT system_id64 FROM pp_systems WHERE name = :name LIMIT 1"),
            {"name": system_name},
        ).fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.warning("Failed to resolve system_id64 for '%s': %s", system_name, e)
        return None


def insert_event(event_data: dict, db_session) -> bool:
    """Insert a PowerplayMerits event into pp_powerplay_events table.

    Returns True if a new row was inserted, False if deduplicated (ON CONFLICT)
    or on error.
    """
    try:
        result = db_session.execute(
            text("""
                INSERT INTO pp_powerplay_events (
                    message_id, uploader_id, event_timestamp, gateway_ts,
                    ingested_at, schema_ref, power, system_name, system_id64,
                    merits, star_pos_x, star_pos_y, star_pos_z
                ) VALUES (
                    :message_id, :uploader_id, :event_timestamp, :gateway_ts,
                    NOW(), :schema_ref, :power, :system_name, :system_id64,
                    :merits, :star_pos_x, :star_pos_y, :star_pos_z
                )
                ON CONFLICT (message_id) DO NOTHING
            """),
            event_data,
        )
        db_session.commit()
        # rowcount == 0 means the ON CONFLICT DO NOTHING clause fired (duplicate)
        return result.rowcount > 0
    except Exception as e:
        logger.error("Failed to insert event: %s", e)
        db_session.rollback()
        return False


def flush_stats_to_db(
    db_session,
    stats: dict,
    listener_started_at: datetime,
    last_event_ts: Optional[datetime],
    events_since_last_flush: int,
    elapsed_seconds: float,
) -> None:
    """Upsert a singleton row (id=1) into eddn_feed_stats with current counters."""
    import json as _json

    # Compute messages/min over the flush interval
    msgs_per_min: Optional[float] = None
    if elapsed_seconds > 0:
        msgs_per_min = round(stats["received_since_last_flush"] / elapsed_seconds * 60.0, 2)

    # Build top-schemas JSON (cap at 10 schemas by count)
    schema_counts: dict = stats.get("schema_counts", {})
    top = sorted(schema_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_schemas_json = _json.dumps(dict(top)) if top else None

    try:
        db_session.execute(
            text("""
                INSERT INTO eddn_feed_stats (
                    id, recorded_at, listener_started_at,
                    events_total, events_last_5min,
                    dedup_rejected, decode_errors, last_event_ts,
                    messages_received_total, bytes_received_total,
                    skipped_schema_total, skipped_event_total,
                    messages_per_min, top_schemas
                ) VALUES (
                    1, NOW(), :started_at,
                    :events_total, :events_last_5min,
                    :dedup_rejected, :decode_errors, :last_event_ts,
                    :msgs_total, :bytes_total,
                    :skipped_schema, :skipped_event,
                    :msgs_per_min, :top_schemas
                )
                ON CONFLICT (id) DO UPDATE SET
                    recorded_at             = EXCLUDED.recorded_at,
                    listener_started_at     = EXCLUDED.listener_started_at,
                    events_total            = EXCLUDED.events_total,
                    events_last_5min        = EXCLUDED.events_last_5min,
                    dedup_rejected          = EXCLUDED.dedup_rejected,
                    decode_errors           = EXCLUDED.decode_errors,
                    last_event_ts           = EXCLUDED.last_event_ts,
                    messages_received_total = EXCLUDED.messages_received_total,
                    bytes_received_total    = EXCLUDED.bytes_received_total,
                    skipped_schema_total    = EXCLUDED.skipped_schema_total,
                    skipped_event_total     = EXCLUDED.skipped_event_total,
                    messages_per_min        = EXCLUDED.messages_per_min,
                    top_schemas             = EXCLUDED.top_schemas
            """),
            {
                "started_at":    listener_started_at,
                "events_total":  stats["inserted"],
                "events_last_5min": events_since_last_flush,
                "dedup_rejected": stats["dedup_rejected"],
                "decode_errors":  stats["decode_errors"],
                "last_event_ts":  last_event_ts,
                "msgs_total":     stats["received"],
                "bytes_total":    stats["bytes_received"],
                "skipped_schema": stats["skipped_schema"],
                "skipped_event":  stats["skipped_event"],
                "msgs_per_min":   msgs_per_min,
                "top_schemas":    top_schemas_json,
            },
        )
        db_session.commit()
    except Exception as e:
        logger.warning("Failed to flush stats to DB: %s", e)
        db_session.rollback()


def _merits_message_id(message: dict) -> str:
    """Dedup key for pp_powerplay_events.

    EDDN headers have no messageID, so derive one from the uploader, the
    gateway timestamp and the message body.
    """
    header = message.get("header", {})
    key = json.dumps(
        [header.get("uploaderID"), header.get("gatewayTimestamp"), message.get("message")],
        sort_keys=True,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def process_merits_message(message: dict, db_session) -> bool:
    """Insert a PowerplayMerits event into pp_powerplay_events.

    Kept in case EDDN ever relays PowerplayMerits; today it never does.
    """
    header = message.get("header", {})
    msg = message.get("message", {})

    power = msg.get("Power")
    system_name = msg.get("System") or msg.get("StarSystem")
    merits = msg.get("Merits")
    event_timestamp = parse_timestamp(msg.get("timestamp", ""))

    # Validate required fields
    if not all([power, system_name, merits, event_timestamp]):
        logger.warning("Missing required fields in PowerplayMerits event: %s", msg)
        return False

    # Extract coordinates (StarPos is [x, y, z])
    star_pos = msg.get("StarPos", [])
    star_pos_x = star_pos[0] if len(star_pos) > 0 else None
    star_pos_y = star_pos[1] if len(star_pos) > 1 else None
    star_pos_z = star_pos[2] if len(star_pos) > 2 else None

    event_data = {
        "message_id": _merits_message_id(message),
        "uploader_id": header.get("uploaderID"),
        "event_timestamp": event_timestamp,
        "gateway_ts": parse_timestamp(header.get("gatewayTimestamp", "")),
        "schema_ref": message.get("$schemaRef", ""),
        "power": power,
        "system_name": system_name,
        "system_id64": resolve_system_id64(system_name, db_session),
        "merits": int(merits),
        "star_pos_x": star_pos_x,
        "star_pos_y": star_pos_y,
        "star_pos_z": star_pos_z,
    }

    success = insert_event(event_data, db_session)
    if success:
        logger.info(
            "Inserted PowerplayMerits event: power=%s, system=%s, merits=%d",
            power, system_name, merits,
        )
    return success


def extract_pp_state(msg: dict) -> Optional[dict]:
    """Pull the Powerplay system state out of an FSDJump/Location/CarrierJump body.

    Returns None for systems with no Powerplay presence, and for Unoccupied
    systems with fewer than two powers (the Spansh ingest skips those too).
    """
    power_state = msg.get("PowerplayState")
    system_id64 = msg.get("SystemAddress")
    name = msg.get("StarSystem")
    event_ts = parse_timestamp(msg.get("timestamp", ""))
    if not power_state or system_id64 is None or not name or event_ts is None:
        return None

    controlling = msg.get("ControllingPower") or None
    powers = msg.get("Powers") or []
    if controlling is None and len(powers) < 2:
        return None
    if controlling is None:
        # Multi-power Unoccupied: stored under the ingest's internal
        # 'Contested' label, which every contested query filters on
        power_state = "Contested"

    # Journal: [{"Power": .., "ConflictProgress": ..}]  ->  Spansh-style
    # [{"power": .., "progress": ..}] as stored by the ingest.
    raw_conflict = msg.get("PowerplayConflictProgress") or []
    conflict = [
        {"power": c.get("Power"), "progress": c.get("ConflictProgress")}
        for c in raw_conflict
        if isinstance(c, dict)
    ]

    star_pos = msg.get("StarPos") or []
    return {
        "system_id64": int(system_id64),
        "name": name,
        "x": star_pos[0] if len(star_pos) > 0 else None,
        "y": star_pos[1] if len(star_pos) > 1 else None,
        "z": star_pos[2] if len(star_pos) > 2 else None,
        "allegiance": msg.get("SystemAllegiance") or None,
        "population": msg.get("Population"),
        "event_ts": event_ts,
        "power": controlling,
        "power_state": power_state,
        "control_progress": msg.get("PowerplayStateControlProgress"),
        "reinforcement": msg.get("PowerplayStateReinforcement"),
        "undermining": msg.get("PowerplayStateUndermining"),
        "powers_list": ",".join(powers) if powers else None,
        "conflict_progress": json.dumps(conflict) if conflict else None,
    }


def _state_fingerprint(state: dict) -> tuple:
    return (
        state["power"], state["power_state"], state["control_progress"],
        state["reinforcement"], state["undermining"],
        state["powers_list"], state["conflict_progress"],
    )


def record_pp_state(state: dict, db_session, cache: dict) -> bool:
    """Insert a pp_system_snapshots row for an observed system state.

    cache maps system_id64 -> {"system_db_id", "event_ts", "fingerprint",
    "written_at"} so repeat sightings of a busy system cost no DB round trip.
    Returns True if a snapshot row was written.
    """
    id64 = state["system_id64"]
    now = time.time()
    fingerprint = _state_fingerprint(state)
    entry = cache.get(id64)

    if entry is not None:
        if state["event_ts"] <= entry["event_ts"]:
            return False
        if (fingerprint == entry["fingerprint"]
                and now - entry["written_at"] < SNAPSHOT_MIN_INTERVAL_SECONDS):
            entry["event_ts"] = state["event_ts"]
            return False

    try:
        if entry is None:
            row = db_session.execute(
                text("SELECT id FROM pp_systems WHERE system_id64 = :id64"),
                {"id64": id64},
            ).fetchone()
            if row is not None:
                system_db_id = row[0]
                # Never write a state older than what is already stored
                latest = db_session.execute(
                    text("""
                        SELECT MAX(spansh_updated_at) FROM pp_system_snapshots
                        WHERE system_id = :sid
                    """),
                    {"sid": system_db_id},
                ).scalar()
                if latest is not None and state["event_ts"] <= latest:
                    db_session.commit()
                    cache[id64] = {
                        "system_db_id": system_db_id, "event_ts": latest,
                        "fingerprint": None, "written_at": 0.0,
                    }
                    return False
            else:
                system_db_id = db_session.execute(
                    text("""
                        INSERT INTO pp_systems (system_id64, name, x, y, z, allegiance, population)
                        VALUES (:id64, :name, :x, :y, :z, :allegiance, :population)
                        ON CONFLICT (system_id64) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                    """),
                    {
                        "id64": id64, "name": state["name"],
                        "x": state["x"], "y": state["y"], "z": state["z"],
                        "allegiance": state["allegiance"], "population": state["population"],
                    },
                ).scalar_one()
        else:
            system_db_id = entry["system_db_id"]

        # CP decay depends only on start-of-cycle progress (mirrors ingestion.py)
        cycle = current_cycle_start()
        cp_decay_val = compute_cp_decay(
            state["power_state"], state["control_progress"],
            state["reinforcement"], state["undermining"],
        )

        # spansh_updated_at means "when the game data was observed"; for a
        # live row that is the journal event time, so the stale filters and
        # data-age displays treat it like any other snapshot.
        db_session.execute(
            text("""
                INSERT INTO pp_system_snapshots
                    (system_id, ingestion_run_id, snapshot_time,
                     spansh_updated_at, power, power_state, control_progress,
                     reinforcement, undermining, powers_list, conflict_progress,
                     cp_decay, decay_cycle_start)
                VALUES
                    (:system_id, NULL, :now, :observed_at, :power, :power_state,
                     :control_progress, :reinforcement, :undermining,
                     :powers_list, :conflict_progress, :cp_decay, :decay_cycle_start)
            """),
            {
                "system_id": system_db_id,
                "now": datetime.utcnow(),
                "observed_at": state["event_ts"],
                "power": state["power"],
                "power_state": state["power_state"],
                "control_progress": state["control_progress"],
                "reinforcement": state["reinforcement"],
                "undermining": state["undermining"],
                "powers_list": state["powers_list"],
                "conflict_progress": state["conflict_progress"],
                "cp_decay": cp_decay_val,
                "decay_cycle_start": cycle,
            },
        )
        db_session.commit()
    except Exception as e:
        logger.error("Failed to record PP state for %s (%d): %s", state["name"], id64, e)
        db_session.rollback()
        return False

    cache[id64] = {
        "system_db_id": system_db_id, "event_ts": state["event_ts"],
        "fingerprint": fingerprint, "written_at": now,
    }
    return True


def process_message(message: dict, db_session, cache: dict, stats: dict) -> None:
    """Route one decoded EDDN message and update the stats counters."""
    if message.get("$schemaRef", "") != EDDN_SCHEMA:
        stats["skipped_schema"] += 1
        return

    msg = message.get("message", {})
    event_type = msg.get("event", "")

    if event_type in STATE_EVENTS:
        state = extract_pp_state(msg)
        if state is None:
            stats["skipped_event"] += 1
            return
        age = (datetime.utcnow() - state["event_ts"]).total_seconds()
        if age > MAX_EVENT_AGE_SECONDS:
            stats["skipped_stale"] += 1
            return
        stats["processed"] += 1
        if record_pp_state(state, db_session, cache):
            stats["inserted"] += 1
            stats["inserted_since_last_flush"] += 1
            stats["last_event_ts"] = state["event_ts"]
        else:
            stats["dedup_rejected"] += 1
        return

    if event_type == TARGET_EVENT:
        stats["processed"] += 1
        if process_merits_message(message, db_session):
            stats["inserted"] += 1
            stats["inserted_since_last_flush"] += 1
            stats["last_event_ts"] = parse_timestamp(msg.get("timestamp", ""))
        else:
            stats["dedup_rejected"] += 1
        return

    stats["skipped_event"] += 1


def _connect(context: zmq.Context) -> zmq.Socket:
    """Open a SUB socket to the relay with TCP keepalive enabled.

    Keepalive lets the kernel notice a dead peer; the silence watchdog in
    main() is the backstop for anything keepalive misses.
    """
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
    socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)
    socket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 15)
    socket.setsockopt(zmq.TCP_KEEPALIVE_CNT, 4)
    socket.setsockopt(zmq.RECONNECT_IVL, 1000)
    socket.setsockopt(zmq.RECONNECT_IVL_MAX, 30000)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all messages
    socket.connect(EDDN_RELAY)
    return socket


def _touch_heartbeat() -> None:
    """Touch the file the k8s liveness probe checks."""
    try:
        open(HEARTBEAT_FILE, "w").close()
    except OSError:
        pass


def _log_and_flush_stats(db_session, stats: dict, listener_started_at: datetime,
                         elapsed: float, final: bool = False) -> None:
    logger.info(
        "%s: received=%d (%.1f/min), processed=%d, inserted=%d, "
        "bytes_recv=%d, dedup_rejected=%d, skipped_schema=%d, "
        "skipped_event=%d, skipped_stale=%d, decode_errors=%d, json_errors=%d, "
        "reconnects=%d",
        "Final stats" if final else "Stats",
        stats["received"],
        stats["received_since_last_flush"] / elapsed * 60.0 if elapsed > 0 else 0.0,
        stats["processed"],
        stats["inserted"],
        stats["bytes_received"],
        stats["dedup_rejected"],
        stats["skipped_schema"],
        stats["skipped_event"],
        stats["skipped_stale"],
        stats["decode_errors"],
        stats["json_errors"],
        stats["reconnects"],
    )
    flush_stats_to_db(
        db_session, stats, listener_started_at,
        stats["last_event_ts"], stats["inserted_since_last_flush"],
        elapsed_seconds=elapsed,
    )
    stats["inserted_since_last_flush"] = 0
    stats["received_since_last_flush"] = 0


def main():
    """Main loop: connect to EDDN relay and process messages."""
    logger.info("Starting EDDN listener...")
    logger.info("Connecting to %s", EDDN_RELAY)
    logger.info("Filtering for schema: %s", EDDN_SCHEMA)
    logger.info("State events: %s (+ %s)", ", ".join(sorted(STATE_EVENTS)), TARGET_EVENT)
    logger.info("Watchdog: reconnect after %ds of silence", WATCHDOG_SILENCE_SECONDS)

    context = zmq.Context()
    socket = _connect(context)

    retry_delay = RETRY_DELAY_INITIAL
    db_session = SessionLocal()
    listener_started_at = datetime.utcnow()
    state_cache: dict = {}

    # Stats counters
    stats = {
        "received": 0,
        "processed": 0,
        "skipped_schema": 0,
        "skipped_event": 0,
        "skipped_stale": 0,
        "decode_errors": 0,
        "json_errors": 0,
        "inserted": 0,
        "dedup_rejected": 0,
        "reconnects": 0,
        # Extended throughput metrics
        "bytes_received": 0,
        "received_since_last_flush": 0,   # messages in the current flush window
        "inserted_since_last_flush": 0,
        "schema_counts": {},              # {schema_ref: count} for top-schemas breakdown
        "last_event_ts": None,
    }
    last_stats_time = time.time()
    last_message_time = time.time()

    _touch_heartbeat()
    try:
        while True:
            try:
                now = time.time()

                # Stats on a timer rather than per message, so a silent feed
                # still shows up in the logs and in eddn_feed_stats.
                if now - last_stats_time >= STATS_LOG_INTERVAL_SECONDS:
                    _log_and_flush_stats(db_session, stats, listener_started_at,
                                         now - last_stats_time)
                    last_stats_time = now

                # Silence watchdog: rebuild the socket if the relay went quiet
                if now - last_message_time >= WATCHDOG_SILENCE_SECONDS:
                    stats["reconnects"] += 1
                    logger.warning(
                        "No EDDN messages for %ds -- reconnecting (reconnect #%d)",
                        int(now - last_message_time), stats["reconnects"],
                    )
                    socket.close(linger=0)
                    socket = _connect(context)
                    last_message_time = now  # give the new socket a full window

                if not socket.poll(timeout=1000):  # 1 second timeout
                    continue

                # EDDN sends multipart messages: [topic_frame, json_frame]
                frames = socket.recv_multipart()
                raw_message = frames[-1]  # Last frame is the JSON payload
                last_message_time = time.time()
                _touch_heartbeat()
                stats["received"] += 1
                stats["bytes_received"] += sum(len(f) for f in frames)
                stats["received_since_last_flush"] += 1

                # Log frame diagnostics at DEBUG level
                logger.debug(
                    "Received %d frame(s), payload len=%d, hex=%s",
                    len(frames),
                    len(raw_message),
                    _hex_preview(raw_message),
                )

                # Decode payload (zlib + UTF-8 with fallback)
                json_text = _decode_payload(raw_message)
                if json_text is None:
                    stats["decode_errors"] += 1
                    continue

                try:
                    message = json.loads(json_text)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Failed to decode JSON message (len=%d): %s",
                        len(json_text),
                        e,
                    )
                    stats["json_errors"] += 1
                    continue

                # Track schema breakdown (count every schema we see)
                schema_ref_seen = message.get("$schemaRef", "unknown")
                stats["schema_counts"][schema_ref_seen] = (
                    stats["schema_counts"].get(schema_ref_seen, 0) + 1
                )

                process_message(message, db_session, state_cache, stats)

                # Reset retry delay on successful receive
                retry_delay = RETRY_DELAY_INITIAL

            except zmq.ZMQError as e:
                logger.error("ZMQ error: %s. Retrying in %d seconds...", e, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, RETRY_DELAY_MAX)

            except Exception as e:
                logger.error("Unexpected error: %s. Retrying in %d seconds...", e, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, RETRY_DELAY_MAX)

    except KeyboardInterrupt:
        logger.info("Shutting down EDDN listener...")
    finally:
        _log_and_flush_stats(db_session, stats, listener_started_at,
                             time.time() - last_stats_time, final=True)
        socket.close()
        context.term()
        db_session.close()
        logger.info("EDDN listener stopped")


if __name__ == "__main__":
    main()
