"""Spansh Power Play bulk ingestion service.

Data source: https://downloads.spansh.co.uk/systems_populated.json.gz

The file is a gzip-compressed JSON array of system objects.  Each object
with a ``controlling_power`` field is a PP-active system.

PP 2.0 schema (confirmed from Spansh API):
{
  "id64": 10477373803,
  "name": "Sol",
  "coords": {"x": 0.0, "y": 0.0, "z": 0.0},
  "allegiance": "Federation",
  "population": 18320926115,
  "controlling_power": "Jerome Archer",
  "power": ["Aisling Duval", "Jerome Archer"],
  "power_state": "Stronghold",
  "power_state_control_progress": 0.649698,
  "power_state_reinforcement": 66756,
  "power_state_undermining": 124458,
  "updated_at": "2026-07-18 03:51:09+00"
}

Systems with no PP presence have null / absent power fields — we skip those.
"""

import gzip
import io
import logging
from datetime import datetime
from typing import Iterator

import ijson
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.models import IngestionRun

logger = logging.getLogger(__name__)

SPANSH_PP_URL = "https://downloads.spansh.co.uk/systems_populated.json.gz"
BATCH_COMMIT_SIZE = 500

# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

# How many compressed bytes to buffer before starting the stream parse.
# Keeping the full file in memory is fine for a ~600 MB download on a server;
# it also avoids the tricky "requests streaming + GzipFile" EOF issue that
# causes ijson to see 0 items when the HTTP connection closes mid-stream.
DOWNLOAD_CHUNK = 1024 * 1024  # 1 MB per chunk


def _download_to_memory(url: str) -> bytes:
    """Download the full .gz file into memory and return the compressed bytes."""
    logger.info("Downloading %s …", url)
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
        if chunk:
            chunks.append(chunk)
            total += len(chunk)
            if total % (50 * DOWNLOAD_CHUNK) == 0:
                logger.info("  … %.0f MB downloaded", total / 1_048_576)

    compressed = b"".join(chunks)
    logger.info("Download complete: %.1f MB compressed", len(compressed) / 1_048_576)
    return compressed


def _detect_ijson_prefix(decompressed_head: bytes) -> str:
    """Peek at the first few bytes to determine the correct ijson prefix.

    Returns 'item' if the root is an array, or '<key>.item' if the root is
    an object whose first value is an array.
    """
    head = decompressed_head.lstrip()
    if head.startswith(b"["):
        return "item"

    if head.startswith(b"{"):
        # Try to find the first string key
        # e.g.  {"systems": [  or  {"data": [
        try:
            import re
            m = re.search(rb'"([^"]+)"\s*:\s*\[', head[:512])
            if m:
                key = m.group(1).decode("utf-8", errors="replace")
                logger.info("Top-level JSON object detected; using prefix '%s.item'", key)
                return f"{key}.item"
        except Exception:
            pass
        logger.warning("Top-level JSON object but could not detect array key; trying 'item'")
        return "item"

    logger.warning("Unexpected JSON prefix: %r; defaulting to 'item'", head[:20])
    return "item"


def _iter_systems(compressed: bytes) -> Iterator[dict]:
    """Decompress and stream-parse system objects from the Spansh dump."""
    decompressed = gzip.decompress(compressed)
    logger.info("Decompressed size: %.1f MB", len(decompressed) / 1_048_576)

    prefix = _detect_ijson_prefix(decompressed[:512])
    logger.info("Using ijson prefix: '%s'", prefix)

    buf = io.BytesIO(decompressed)
    yield from ijson.items(buf, prefix)


# ---------------------------------------------------------------------------
# Main ingest entry point
# ---------------------------------------------------------------------------


def run_spansh_ingest(db: Session) -> IngestionRun:
    """Download the Spansh systems_populated dump and store PP snapshots.

    Only systems that have a non-null ``controlling_power`` are stored.
    Inserts one pp_system_snapshots row per system per call (insert-only,
    never updated) so the full history accumulates for trend analysis.
    """
    run = IngestionRun(
        source="spansh_pp",
        status="running",
        started_at=datetime.utcnow(),
        records_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id: int = run.id
    logger.info("Spansh PP ingest started (run_id=%d)", run_id)

    records_processed = 0
    total_seen = 0

    try:
        compressed = _download_to_memory(SPANSH_PP_URL)
        logger.info("Parsing system objects …")

        for system_obj in _iter_systems(compressed):
            total_seen += 1

            # Log the first object's keys so we can verify the schema
            if total_seen == 1:
                logger.info(
                    "First system object keys: %s",
                    list(system_obj.keys()) if isinstance(system_obj, dict) else type(system_obj),
                )
                if isinstance(system_obj, dict):
                    logger.info(
                        "First system PP fields — controlling_power=%r  power_state=%r  power=%r",
                        system_obj.get("controlling_power"),
                        system_obj.get("power_state"),
                        system_obj.get("power"),
                    )

            if total_seen % 50_000 == 0:
                logger.info(
                    "  … %d total systems scanned, %d PP systems stored",
                    total_seen, records_processed,
                )

            if not isinstance(system_obj, dict):
                continue

            # Skip systems with no PP controlling power
            controlling_power: str | None = system_obj.get("controlling_power")
            if not controlling_power:
                continue

            system_id64: int | None = system_obj.get("id64")
            if system_id64 is None:
                continue

            name: str = system_obj.get("name", "")

            # coords may be a nested dict {"x": ..., "y": ..., "z": ...}
            # or flat top-level keys — handle both
            coords = system_obj.get("coords")
            if isinstance(coords, dict):
                x: float | None = coords.get("x")
                y: float | None = coords.get("y")
                z: float | None = coords.get("z")
            else:
                x = system_obj.get("x")
                y = system_obj.get("y")
                z = system_obj.get("z")

            allegiance: str | None = system_obj.get("allegiance")
            population: int | None = system_obj.get("population")
            power_state: str | None = system_obj.get("power_state")
            control_progress: float | None = system_obj.get("power_state_control_progress")
            reinforcement: int | None = system_obj.get("power_state_reinforcement")
            undermining: int | None = system_obj.get("power_state_undermining")

            # Upsert the system record
            sys_result = db.execute(
                text("""
                    INSERT INTO pp_systems (system_id64, name, x, y, z, allegiance, population)
                    VALUES (:id64, :name, :x, :y, :z, :allegiance, :population)
                    ON CONFLICT (system_id64) DO UPDATE
                        SET name       = EXCLUDED.name,
                            x          = EXCLUDED.x,
                            y          = EXCLUDED.y,
                            z          = EXCLUDED.z,
                            allegiance = EXCLUDED.allegiance,
                            population = EXCLUDED.population
                    RETURNING id
                """),
                {
                    "id64": system_id64, "name": name,
                    "x": x, "y": y, "z": z,
                    "allegiance": allegiance, "population": population,
                },
            )
            system_db_id: int = sys_result.scalar_one()

            # Insert a fresh snapshot row (insert-only for full history)
            db.execute(
                text("""
                    INSERT INTO pp_system_snapshots
                        (system_id, ingestion_run_id, snapshot_time,
                         power, power_state, control_progress,
                         reinforcement, undermining)
                    VALUES
                        (:system_id, :run_id, :now,
                         :power, :power_state, :control_progress,
                         :reinforcement, :undermining)
                """),
                {
                    "system_id": system_db_id,
                    "run_id": run_id,
                    "now": datetime.utcnow(),
                    "power": controlling_power,
                    "power_state": power_state,
                    "control_progress": control_progress,
                    "reinforcement": reinforcement,
                    "undermining": undermining,
                },
            )

            records_processed += 1
            if records_processed % BATCH_COMMIT_SIZE == 0:
                db.commit()
                logger.debug("Committed batch; %d PP systems stored so far", records_processed)

        db.commit()
        logger.info(
            "Parse complete: %d total systems scanned, %d PP systems stored (run_id=%d)",
            total_seen, records_processed, run_id,
        )

        if total_seen == 0:
            logger.error(
                "ZERO systems were yielded by ijson — the JSON prefix is likely wrong. "
                "Run probe_spansh.py on the server to inspect the file structure."
            )

        db.execute(
            text("""
                UPDATE ingestion_runs
                SET status = 'completed', completed_at = :now, records_processed = :count
                WHERE id = :run_id
            """),
            {"now": datetime.utcnow(), "count": records_processed, "run_id": run_id},
        )
        db.commit()
        db.refresh(run)

    except Exception:
        logger.exception("Spansh PP ingest failed (run_id=%d)", run_id)
        try:
            db.execute(
                text("UPDATE ingestion_runs SET status = 'failed' WHERE id = :id"),
                {"id": run_id},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise

    return run
