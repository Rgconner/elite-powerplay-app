"""EDDN ZeroMQ Listener for PowerplayMerits events.

Subscribes to the EDDN relay (tcp://eddn.edcd.io:9500) and filters for
PowerplayMerits journal events. Deduplicates by messageID, resolves
system_id64 from pp_systems table, and inserts raw events into
pp_powerplay_events table.

Runs as an isolated k8s deployment, separate from the main backend.
"""

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
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# EDDN connection - env-configurable with defaults
EDDN_RELAY = os.getenv("EDDN_RELAY_URL", "tcp://eddn.edcd.io:9500")
EDDN_SCHEMA = os.getenv("EDDN_SCHEMA_URL", "https://eddn.edcd.io/schemas/journal/1")
TARGET_EVENT = os.getenv("TARGET_EVENT", "PowerplayMerits")

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
    """Insert a PowerplayMerits event into pp_powerplay_events table."""
    try:
        db_session.execute(
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
        return True
    except Exception as e:
        logger.error("Failed to insert event: %s", e)
        db_session.rollback()
        return False


def process_message(message: dict, db_session) -> bool:
    """Process a single EDDN message and insert if it's a PowerplayMerits event."""
    # Check schema
    schema_ref = message.get("$schemaRef", "")
    if schema_ref != EDDN_SCHEMA:
        return False

    # Extract header fields
    header = message.get("header", {})
    message_id = header.get("messageID")
    uploader_id = header.get("uploaderID")
    gateway_ts = parse_timestamp(header.get("gatewayTimestamp", ""))

    if not message_id:
        logger.warning("Message missing messageID, skipping")
        return False

    # Extract message fields
    msg = message.get("message", {})
    event_type = msg.get("event", "")

    # Filter for PowerplayMerits events only
    if event_type != TARGET_EVENT:
        return False

    # Extract PowerplayMerits-specific fields
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

    # Resolve system_id64 from database
    system_id64 = resolve_system_id64(system_name, db_session)

    # Prepare event data
    event_data = {
        "message_id": message_id,
        "uploader_id": uploader_id,
        "event_timestamp": event_timestamp,
        "gateway_ts": gateway_ts,
        "schema_ref": schema_ref,
        "power": power,
        "system_name": system_name,
        "system_id64": system_id64,
        "merits": int(merits),
        "star_pos_x": star_pos_x,
        "star_pos_y": star_pos_y,
        "star_pos_z": star_pos_z,
    }

    # Insert into database
    success = insert_event(event_data, db_session)
    if success:
        logger.info(
            "Inserted PowerplayMerits event: power=%s, system=%s, merits=%d",
            power, system_name, merits,
        )
    return success


def main():
    """Main loop: connect to EDDN relay and process messages."""
    logger.info("Starting EDDN listener...")
    logger.info("Connecting to %s", EDDN_RELAY)
    logger.info("Filtering for schema: %s", EDDN_SCHEMA)
    logger.info("Target event: %s", TARGET_EVENT)

    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(EDDN_RELAY)
    socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all messages

    retry_delay = RETRY_DELAY_INITIAL
    db_session = SessionLocal()

    # Stats counters
    stats = {
        "received": 0,
        "processed": 0,
        "skipped_schema": 0,
        "skipped_event": 0,
        "skipped_fields": 0,
        "decode_errors": 0,
        "json_errors": 0,
        "inserted": 0,
    }
    last_stats_time = time.time()

    HEARTBEAT_FILE = "/tmp/eddn_heartbeat"
    try:
        while True:
            # Write heartbeat timestamp — checked by the k8s liveness probe.
            try:
                open(HEARTBEAT_FILE, "w").close()
            except OSError:
                pass

            try:
                # Receive message with timeout
                if socket.poll(timeout=1000):  # 1 second timeout
                    # EDDN sends multipart messages: [topic_frame, json_frame]
                    frames = socket.recv_multipart()
                    raw_message = frames[-1]  # Last frame is the JSON payload
                    stats["received"] += 1

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

                    # Process the message
                    success = process_message(message, db_session)
                    if not success:
                        # Track skip reasons
                        schema_ref = message.get("$schemaRef", "")
                        if schema_ref != EDDN_SCHEMA:
                            stats["skipped_schema"] += 1
                        else:
                            msg = message.get("message", {})
                            event_type = msg.get("event", "")
                            if event_type != TARGET_EVENT:
                                stats["skipped_event"] += 1
                            else:
                                stats["skipped_fields"] += 1
                    else:
                        stats["processed"] += 1
                        stats["inserted"] += 1

                    # Reset retry delay on successful receive
                    retry_delay = RETRY_DELAY_INITIAL

                    # Periodic stats logging
                    now = time.time()
                    if now - last_stats_time >= STATS_LOG_INTERVAL_SECONDS:
                        logger.info(
                            "Stats: received=%d, processed=%d, inserted=%d, "
                            "skipped_schema=%d, skipped_event=%d, skipped_fields=%d, "
                            "decode_errors=%d, json_errors=%d",
                            stats["received"],
                            stats["processed"],
                            stats["inserted"],
                            stats["skipped_schema"],
                            stats["skipped_event"],
                            stats["skipped_fields"],
                            stats["decode_errors"],
                            stats["json_errors"],
                        )
                        last_stats_time = now
                else:
                    # No message received, just continue
                    continue

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
        # Final stats log
        logger.info(
            "Final stats: received=%d, processed=%d, inserted=%d, "
            "skipped_schema=%d, skipped_event=%d, skipped_fields=%d, "
            "decode_errors=%d, json_errors=%d",
            stats["received"],
            stats["processed"],
            stats["inserted"],
            stats["skipped_schema"],
            stats["skipped_event"],
            stats["skipped_fields"],
            stats["decode_errors"],
            stats["json_errors"],
        )
        socket.close()
        context.term()
        db_session.close()
        logger.info("EDDN listener stopped")


if __name__ == "__main__":
    main()