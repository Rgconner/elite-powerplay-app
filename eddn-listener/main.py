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
from datetime import datetime
from typing import Optional

import zmq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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

# EDDN connection
EDDN_RELAY = "tcp://eddn.edcd.io:9500"
EDDN_SCHEMA = "https://eddn.edcd.io/schemas/journal/1"
TARGET_EVENT = "PowerplayMerits"

# Retry configuration
RETRY_DELAY_INITIAL = 1
RETRY_DELAY_MAX = 30


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

    try:
        while True:
            try:
                # Receive message with timeout
                if socket.poll(timeout=1000):  # 1 second timeout
                    # EDDN sends multipart messages: [topic_frame, json_frame]
                    frames = socket.recv_multipart()
                    raw_message = frames[-1]  # Last frame is the JSON payload
                    message = json.loads(raw_message.decode("utf-8"))

                    # Process the message
                    process_message(message, db_session)

                    # Reset retry delay on successful receive
                    retry_delay = RETRY_DELAY_INITIAL
                else:
                    # No message received, just continue
                    continue

            except zmq.ZMQError as e:
                logger.error("ZMQ error: %s. Retrying in %d seconds...", e, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, RETRY_DELAY_MAX)

            except UnicodeDecodeError as e:
                logger.warning("Failed to decode message as UTF-8: %s", e)
                continue

            except json.JSONDecodeError as e:
                logger.warning("Failed to decode JSON message: %s", e)
                continue

            except Exception as e:
                logger.error("Unexpected error: %s. Retrying in %d seconds...", e, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, RETRY_DELAY_MAX)

    except KeyboardInterrupt:
        logger.info("Shutting down EDDN listener...")
    finally:
        socket.close()
        context.term()
        db_session.close()
        logger.info("EDDN listener stopped")


if __name__ == "__main__":
    main()