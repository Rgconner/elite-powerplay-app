"""Spansh factions.json.gz streaming ingestion service.

Downloads and parses the Spansh bulk faction dump on-the-fly using ijson so
the full (potentially hundreds-of-MB) file is never held in RAM.
"""

import gzip
import logging
from datetime import datetime

import ijson
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.models import IngestionRun

logger = logging.getLogger(__name__)

SPANSH_URL = "https://downloads.spansh.co.uk/factions.json.gz"
BATCH_COMMIT_SIZE = 1000


def _deduplicate_systems(systems: list) -> list:
    """Deduplicate a faction's systems list by systemId64.

    The Spansh dump lists a system twice when the faction controls it — once
    with isControllingFaction=true and once without.  Keep the controlling
    entry when it exists; otherwise keep the first occurrence.
    """
    seen: dict[int, dict] = {}
    for entry in systems:
        sid = entry.get("systemId64")
        if sid is None:
            continue
        if sid not in seen:
            seen[sid] = entry
        else:
            # Prefer the entry where isControllingFaction is True
            if entry.get("isControllingFaction", False):
                seen[sid] = entry
    return list(seen.values())


def run_spansh_ingest(db: Session) -> IngestionRun:
    """Stream-download and ingest the Spansh factions dump into PostgreSQL.

    Creates an IngestionRun audit row, processes every faction record via
    ijson (one at a time), upserts factions/systems, inserts faction_presence
    rows tied to this run, and updates the run status on completion or failure.

    Returns the completed IngestionRun ORM object.
    """
    # ------------------------------------------------------------------
    # 1. Create the ingestion_run row so we have an ID to link against.
    # ------------------------------------------------------------------
    run = IngestionRun(
        source="spansh",
        status="running",
        started_at=datetime.utcnow(),
        records_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id: int = run.id

    records_processed = 0

    try:
        # ------------------------------------------------------------------
        # 2. Open the HTTPS stream and wrap with on-the-fly gzip decompression.
        # ------------------------------------------------------------------
        logger.info("Starting Spansh factions download from %s", SPANSH_URL)
        response = requests.get(SPANSH_URL, stream=True, timeout=60)
        response.raise_for_status()
        # Required so urllib3 decompresses transfer-encoding automatically
        # when we pass raw to GzipFile.
        response.raw.decode_content = True
        gzip_file = gzip.GzipFile(fileobj=response.raw, mode="rb")

        # ------------------------------------------------------------------
        # 3. Stream-parse with ijson — yields one faction dict at a time.
        # ------------------------------------------------------------------
        for faction_obj in ijson.items(gzip_file, "item"):
            faction_name: str = faction_obj.get("name", "")
            if not faction_name:
                continue

            allegiance: str | None = faction_obj.get("allegiance")
            government: str | None = faction_obj.get("government")

            # ── Upsert faction ──────────────────────────────────────────
            result = db.execute(
                text(
                    """
                    INSERT INTO factions (name, allegiance, government)
                    VALUES (:name, :allegiance, :government)
                    ON CONFLICT (name) DO UPDATE
                        SET allegiance = EXCLUDED.allegiance,
                            government = EXCLUDED.government
                    RETURNING id
                    """
                ),
                {"name": faction_name, "allegiance": allegiance, "government": government},
            )
            faction_id: int = result.scalar_one()

            # ── Deduplicate and process systems ─────────────────────────
            raw_systems: list = faction_obj.get("systems", [])
            deduped_systems = _deduplicate_systems(raw_systems)

            for sys_entry in deduped_systems:
                system_id64: int | None = sys_entry.get("systemId64")
                if system_id64 is None:
                    continue

                system_name: str = sys_entry.get("name", "")
                x: float | None = sys_entry.get("x")
                y: float | None = sys_entry.get("y")
                z: float | None = sys_entry.get("z")
                is_controlling: bool = bool(sys_entry.get("isControllingFaction", False))

                # Upsert system by system_id64
                sys_result = db.execute(
                    text(
                        """
                        INSERT INTO systems (system_id64, name, x, y, z)
                        VALUES (:system_id64, :name, :x, :y, :z)
                        ON CONFLICT (system_id64) DO UPDATE
                            SET name = EXCLUDED.name,
                                x    = EXCLUDED.x,
                                y    = EXCLUDED.y,
                                z    = EXCLUDED.z
                        RETURNING id
                        """
                    ),
                    {
                        "system_id64": system_id64,
                        "name": system_name,
                        "x": x,
                        "y": y,
                        "z": z,
                    },
                )
                system_id: int = sys_result.scalar_one()

                # Insert faction_presence row (fresh per run; not upserted)
                db.execute(
                    text(
                        """
                        INSERT INTO faction_presence
                            (faction_id, system_id, is_controlling, ingestion_run_id)
                        VALUES (:faction_id, :system_id, :is_controlling, :run_id)
                        """
                    ),
                    {
                        "faction_id": faction_id,
                        "system_id": system_id,
                        "is_controlling": is_controlling,
                        "run_id": run_id,
                    },
                )

            records_processed += 1

            # Commit in batches to avoid a massive open transaction.
            if records_processed % BATCH_COMMIT_SIZE == 0:
                db.commit()
                logger.debug("Spansh ingest: %d factions processed", records_processed)

        # ------------------------------------------------------------------
        # 4. Final commit + mark run as completed.
        # ------------------------------------------------------------------
        db.execute(
            text(
                """
                UPDATE ingestion_runs
                SET status = 'completed',
                    completed_at = :now,
                    records_processed = :count
                WHERE id = :run_id
                """
            ),
            {"now": datetime.utcnow(), "count": records_processed, "run_id": run_id},
        )
        db.commit()
        db.refresh(run)
        logger.info(
            "Spansh ingest completed: %d factions processed (run_id=%d)",
            records_processed,
            run_id,
        )

    except Exception:
        # Mark run as failed; re-raise so the caller/scheduler can log it.
        logger.exception("Spansh ingest failed (run_id=%d)", run_id)
        try:
            db.execute(
                text(
                    "UPDATE ingestion_runs SET status = 'failed' WHERE id = :run_id"
                ),
                {"run_id": run_id},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise

    return run
