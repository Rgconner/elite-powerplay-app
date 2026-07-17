"""EDSM Power Play sync service.

Queries EDSM for Power Play state and controlling faction influence for every
system in the ``systems`` table, then inserts a time-stamped row into
``pp_snapshots``.

Design notes
------------
* Synchronous — runs inside APScheduler's BackgroundScheduler thread pool, NOT
  in an async event loop.  Uses ``httpx.Client`` (sync) throughout.
* Rate-limited to ~1 request/sec between systems (two HTTP calls per system
  count as one "system unit" for rate-limiting purposes).
* INSERT-only: never upserts ``pp_snapshots``; every sync appends new rows so
  historical trends accumulate over time.
* Errors per system are logged as warnings; a snapshot row with NULL fields is
  still inserted so the audit trail shows the sync attempted that system.
"""

import logging
import time
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from models.models import IngestionRun, PPSnapshot, System

logger = logging.getLogger(__name__)

_EDSM_SYSTEM_URL = (
    "https://www.edsm.net/api-v1/system"
)
_EDSM_FACTIONS_URL = (
    "https://www.edsm.net/api-system-v1/factions"
)
_USER_AGENT = "ElitePowerPlayAnalyzer/1.0"
_HTTP_TIMEOUT = 10.0  # seconds
_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_edsm_sync(db: Session) -> IngestionRun:
    """Query EDSM for PP data for all known systems and store snapshots.

    Creates an :class:`~models.models.IngestionRun` row, iterates every row in
    the ``systems`` table, fetches Power Play state + faction influence from
    EDSM, and inserts a :class:`~models.models.PPSnapshot` row for each.

    Returns the completed (or failed) ``IngestionRun`` ORM object.
    """
    # --- create audit record ---------------------------------------------------
    run = IngestionRun(
        source="edsm",
        status="running",
        started_at=datetime.utcnow(),
        records_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    logger.info("EDSM sync started (run_id=%d).", run.id)

    try:
        systems = db.query(System).all()
        total = len(systems)
        logger.info("EDSM sync: %d systems to process.", total)

        counter = 0

        with httpx.Client(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            for idx, system in enumerate(systems):
                pp_power, pp_state, controlling_influence = _fetch_system_data(
                    client, system.name
                )

                snapshot = PPSnapshot(
                    system_id=system.id,
                    pp_power=pp_power,
                    pp_state=pp_state,
                    influence=controlling_influence,
                    snapshot_time=datetime.utcnow(),
                    ingestion_run_id=run.id,
                )
                db.add(snapshot)
                counter += 1

                # Commit in batches of _BATCH_SIZE to avoid holding a huge
                # transaction open for the full sync.
                if counter % _BATCH_SIZE == 0:
                    db.commit()
                    logger.debug(
                        "EDSM sync: committed batch at %d/%d systems.", counter, total
                    )

                # Rate-limit: sleep between systems (not between the two calls
                # for the same system).  Skip the sleep after the last system.
                if idx < total - 1:
                    time.sleep(1)

        # Commit any remaining rows in the final partial batch.
        db.commit()

        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.records_processed = counter
        db.commit()
        logger.info(
            "EDSM sync completed (run_id=%d): %d snapshots inserted.",
            run.id,
            counter,
        )

    except Exception:
        logger.exception("EDSM sync failed (run_id=%d).", run.id)
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        db.commit()
        raise

    return run


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fetch_system_data(
    client: httpx.Client,
    system_name: str,
) -> tuple[str | None, str | None, float | None]:
    """Fetch PP state and controlling faction influence for one system.

    Returns a ``(pp_power, pp_state, controlling_influence)`` tuple.  Any
    field is ``None`` when EDSM doesn't provide it or an error occurs.
    """
    pp_power: str | None = None
    pp_state: str | None = None
    controlling_influence: float | None = None

    # --- Call 1: PP state ----------------------------------------------------
    try:
        resp = client.get(
            _EDSM_SYSTEM_URL,
            params={
                "systemName": system_name,
                "showPowerPlay": "1",
                "showInformation": "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        powers = data.get("powers")
        if powers:
            pp_power = powers[0]
        pp_state = data.get("powerState")
    except Exception as exc:
        logger.warning(
            "EDSM PP-state call failed for system %r: %s", system_name, exc
        )

    # --- Call 2: faction influence -------------------------------------------
    try:
        resp = client.get(
            _EDSM_FACTIONS_URL,
            params={"systemName": system_name},
        )
        resp.raise_for_status()
        data = resp.json()
        factions = data.get("factions") or []
        for faction in factions:
            if faction.get("isControllingFaction"):
                controlling_influence = faction.get("influence")
                break
    except Exception as exc:
        logger.warning(
            "EDSM factions call failed for system %r: %s", system_name, exc
        )

    return pp_power, pp_state, controlling_influence
