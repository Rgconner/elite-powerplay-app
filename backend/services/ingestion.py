"""Spansh Power Play ingestion service — uses the Spansh search API.

Data source: POST https://spansh.co.uk/api/systems/search
             with filter controlling_power = <power name>

This is the correct source for PP 2.0 data.  The bulk download files
(systems_populated.json.gz, galaxy.json.gz) do NOT contain PP fields.

Actual PP 2.0 schema from the Spansh API (confirmed 2026-07):
{
  "id64": 203174175932,
  "name": "52 h2 Sagittarii",
  "x": -46.0,
  "y": -68.3125,
  "z": 170.8125,
  "allegiance": "Independent",
  "population": 68496,
  "controlling_power": "Aisling Duval",
  "power": ["Aisling Duval"],
  "power_state": "Exploited",         -- Exploited | Fortified | Stronghold | Unoccupied
  "power_state_control_progress": 0.259166,
  "power_state_reinforcement": 0,
  "power_state_undermining": 291,
  "updated_at": "2026-07-17 18:46:04+00"
}

Coords are FLAT (x/y/z at top level, not nested).
Power name for Arissa is "A. Lavigny-Duval" (abbreviated), not full name.

Known powers (from field_values endpoint, July 2026):
  A. Lavigny-Duval, Aisling Duval, Archon Delaine, Denton Patreus,
  Edmund Mahon, Felicia Winters, Jerome Archer, Li Yong-Rui,
  Nakato Kaine, Pranav Antal, Yuri Grom, Zemina Torval

Known PP states (from field_values endpoint):
  Exploited (13,263 systems), Fortified (2,827), Stronghold (1,414),
  Unoccupied (34,949 — systems with PP presence but no controlling power)

We ingest ALL powers in a single run so the full galaxy picture is available.
For each power we page through the search API 500 systems at a time.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.models import IngestionRun


def _extract_powers_fields(system_obj: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract powers_list and conflict_progress strings from a Spansh system record.

    Spansh returns:
      "power": ["A. Lavigny-Duval", "Aisling Duval", ...]  -- list of powers in-sphere
      "power_conflict_progress": [{"power": "A. Lavigny-Duval", "progress": 1.46}, ...]

    We store:
      powers_list       = "A. Lavigny-Duval,Aisling Duval,..."  (queryable with LIKE/ILIKE)
      conflict_progress = JSON string of the power_conflict_progress array
    """
    raw_power = system_obj.get("power")
    if isinstance(raw_power, list) and raw_power:
        powers_list: Optional[str] = ",".join(str(p) for p in raw_power)
    elif isinstance(raw_power, str) and raw_power:
        powers_list = raw_power
    else:
        powers_list = None

    raw_cp = system_obj.get("power_conflict_progress")
    if raw_cp:
        try:
            conflict_progress: Optional[str] = json.dumps(raw_cp)
        except Exception:
            conflict_progress = None
    else:
        conflict_progress = None

    return powers_list, conflict_progress

logger = logging.getLogger(__name__)

SPANSH_SEARCH_URL = "https://spansh.co.uk/api/systems/search"
PAGE_SIZE = 500          # max Spansh allows per request
REQUEST_DELAY = 0.25     # seconds between pages — be polite to Spansh
BATCH_COMMIT_SIZE = 500  # DB commit frequency

# All known powers as of July 2026 (abbreviated names as Spansh returns them)
ALL_POWERS = [
    "A. Lavigny-Duval",
    "Aisling Duval",
    "Archon Delaine",
    "Denton Patreus",
    "Edmund Mahon",
    "Felicia Winters",
    "Jerome Archer",
    "Li Yong-Rui",
    "Nakato Kaine",
    "Pranav Antal",
    "Yuri Grom",
    "Zemina Torval",
]

# ---------------------------------------------------------------------------
# Why Contested systems need a separate pass
# ---------------------------------------------------------------------------
# The main ingest loop queries Spansh with filter: controlling_power = <power>.
# Contested systems may have NO single controlling_power (or the controller is
# ambiguous / rotating), so they are NOT returned by that filter and never enter
# the DB via the main loop.
#
# Spansh DOES support filtering by power_state directly.  We run a second pass
# after the main loop to fetch all systems currently in Contested state,
# regardless of which power controls them.  This ensures:
#   - Contested systems appear in pp_system_snapshots with power_state='Contested'
#   - The /api/powers/{name}/contested endpoint returns current live data
#   - Systems that leave Contested state will be overwritten on next ingest
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Spansh API helpers
# ---------------------------------------------------------------------------


def _fetch_page_by_power(power: str, page: int) -> dict:
    """Fetch one page of systems for a power (controlling_power filter)."""
    payload = {
        "filters": {
            "controlling_power": {"value": [power], "comparison": "="}
        },
        "size": PAGE_SIZE,
        "page": page,
        "sort": [{"id64": {"direction": "asc"}}],
    }
    resp = requests.post(SPANSH_SEARCH_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _fetch_page_unoccupied(page: int) -> dict:
    """Fetch one page of Unoccupied systems that have multiple powers present.

    These are the 'contested' systems in PP2.0: power_state=Unoccupied but
    power[] contains 2+ entries, indicating multiple powers vying for control.
    Spansh does NOT have a 'Contested' state — the multi-power Unoccupied
    state IS the contested representation.
    """
    payload = {
        "filters": {
            "power_state": {"value": ["Unoccupied"], "comparison": "="}
        },
        "size": PAGE_SIZE,
        "page": page,
        "sort": [{"id64": {"direction": "asc"}}],
    }
    resp = requests.post(SPANSH_SEARCH_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _iter_power_systems(power: str):
    """Yield all system dicts for a given power, paging through the API."""
    page = 0
    total_reported = None

    while True:
        logger.debug("Fetching page %d for power '%s'", page, power)
        data = _fetch_page_by_power(power, page)

        if total_reported is None:
            total_reported = data.get("count", 0)
            logger.info("  Power '%s': %d systems reported by API", power, total_reported)

        results = data.get("results", [])
        if not results:
            break

        yield from results
        page += 1

        # Stop if we've seen all systems (avoid infinite loop on API quirks)
        if total_reported is not None and (page * PAGE_SIZE) >= total_reported:
            break

        time.sleep(REQUEST_DELAY)


def _iter_unoccupied_systems():
    """Yield all Unoccupied systems from the Spansh API.

    PP2.0 contested systems appear as Unoccupied with a 'power' list containing
    2+ power names and a 'power_conflict_progress' array.  We ingest all Unoccupied
    systems so we can detect multi-power entries in post-processing.

    Note: there are ~35,000 Unoccupied systems — this pass takes a few minutes.
    """
    page = 0
    total_reported = None

    while True:
        logger.debug("Fetching Unoccupied systems page %d", page)
        data = _fetch_page_unoccupied(page)

        if total_reported is None:
            total_reported = data.get("count", 0)
            logger.info("  Unoccupied systems: %d reported by API", total_reported)

        results = data.get("results", [])
        if not results:
            break

        # Only yield systems with 2+ powers (the genuinely contested ones)
        # to avoid ingesting tens of thousands of irrelevant Unoccupied rows.
        for r in results:
            raw_p = r.get("power")
            if isinstance(raw_p, list) and len(raw_p) >= 2:
                yield r

        page += 1

        if total_reported is not None and (page * PAGE_SIZE) >= total_reported:
            break

        time.sleep(REQUEST_DELAY)


# ---------------------------------------------------------------------------
# Main ingest entry point
# ---------------------------------------------------------------------------


def run_spansh_ingest(db: Session) -> IngestionRun:
    """Fetch PP system data from the Spansh search API and store snapshots.

    Iterates over all known Powers, paging through the Spansh search API
    500 systems at a time.  Inserts one pp_system_snapshots row per system
    per call (insert-only) so the full history accumulates.
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
    logger.info("Spansh PP ingest started via search API (run_id=%d)", run_id)

    records_processed = 0

    try:
        for power in ALL_POWERS:
            logger.info("Ingesting power: %s", power)
            power_count = 0

            for system_obj in _iter_power_systems(power):
                system_id64: Optional[int] = system_obj.get("id64")
                if system_id64 is None:
                    continue

                name: str = system_obj.get("name", "")

                # Coords are flat in the API response
                x: Optional[float] = system_obj.get("x")
                y: Optional[float] = system_obj.get("y")
                z: Optional[float] = system_obj.get("z")
                # Fallback: try nested coords dict (future-proofing)
                if x is None:
                    coords = system_obj.get("coords") or {}
                    x = coords.get("x")
                    y = coords.get("y")
                    z = coords.get("z")

                allegiance: Optional[str]  = system_obj.get("allegiance")
                population: Optional[int]  = system_obj.get("population")
                power_state: Optional[str] = system_obj.get("power_state")
                control_progress: Optional[float] = system_obj.get("power_state_control_progress")
                reinforcement: Optional[int] = system_obj.get("power_state_reinforcement")
                undermining: Optional[int]   = system_obj.get("power_state_undermining")
                powers_list, conflict_progress = _extract_powers_fields(system_obj)

                # Parse Spansh's updated_at (e.g. "2026-07-17 18:46:04+00")
                spansh_updated_at: Optional[datetime] = None
                raw_updated = system_obj.get("updated_at")
                if raw_updated:
                    try:
                        spansh_updated_at = datetime.fromisoformat(
                            str(raw_updated).replace("+00", "+00:00")
                        ).replace(tzinfo=None)  # store as naive UTC
                    except Exception:
                        pass

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

                # Insert a fresh snapshot row (insert-only for history)
                db.execute(
                    text("""
                        INSERT INTO pp_system_snapshots
                            (system_id, ingestion_run_id, snapshot_time,
                             spansh_updated_at,
                             power, power_state, control_progress,
                             reinforcement, undermining,
                             powers_list, conflict_progress)
                        VALUES
                            (:system_id, :run_id, :now,
                             :spansh_updated_at,
                             :power, :power_state, :control_progress,
                             :reinforcement, :undermining,
                             :powers_list, :conflict_progress)
                    """),
                    {
                        "system_id":          system_db_id,
                        "run_id":             run_id,
                        "now":                datetime.utcnow(),
                        "spansh_updated_at":  spansh_updated_at,
                        "power":              power,
                        "power_state":        power_state,
                        "control_progress":   control_progress,
                        "reinforcement":      reinforcement,
                        "undermining":        undermining,
                        "powers_list":        powers_list,
                        "conflict_progress":  conflict_progress,
                    },
                )

                records_processed += 1
                power_count += 1
                if records_processed % BATCH_COMMIT_SIZE == 0:
                    db.commit()
                    logger.debug("  … %d total records committed", records_processed)

            db.commit()
            logger.info("  Finished '%s': %d systems stored", power, power_count)

        # ── Second pass: Multi-power Unoccupied (Contested) systems ──────────
        # In PP2.0, a system being fought over by multiple powers appears as:
        #   power_state = "Unoccupied"
        #   power       = ["A. Lavigny-Duval", "Aisling Duval", ...]  (2+ entries)
        #   power_conflict_progress = [{power:..., progress:...}, ...]
        #
        # We store these with power_state='Contested' (our internal label) so
        # the /contested endpoint can find them with a simple WHERE clause.
        # powers_list and conflict_progress capture the full multi-power data.
        logger.info("Starting multi-power Unoccupied (Contested) pass...")
        contested_count = 0
        for system_obj in _iter_unoccupied_systems():
            system_id64_c: Optional[int] = system_obj.get("id64")
            if system_id64_c is None:
                continue

            name_c    = system_obj.get("name", "")
            xc        = system_obj.get("x")
            yc        = system_obj.get("y")
            zc        = system_obj.get("z")
            if xc is None:
                coords_c = system_obj.get("coords") or {}
                xc = coords_c.get("x"); yc = coords_c.get("y"); zc = coords_c.get("z")

            allegiance_c       = system_obj.get("allegiance")
            population_c       = system_obj.get("population")
            control_progress_c = system_obj.get("power_state_control_progress")
            reinforcement_c    = system_obj.get("power_state_reinforcement")
            undermining_c      = system_obj.get("power_state_undermining")
            powers_list_c, conflict_progress_c = _extract_powers_fields(system_obj)

            # Parse Spansh's updated_at
            spansh_updated_at_c: Optional[datetime] = None
            raw_updated_c = system_obj.get("updated_at")
            if raw_updated_c:
                try:
                    spansh_updated_at_c = datetime.fromisoformat(
                        str(raw_updated_c).replace("+00", "+00:00")
                    ).replace(tzinfo=None)
                except Exception:
                    pass

            # Use None for controlling power — no single owner in contested state
            # power_state stored as 'Contested' (our internal label)
            sys_result_c = db.execute(
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
                    "id64": system_id64_c, "name": name_c,
                    "x": xc, "y": yc, "z": zc,
                    "allegiance": allegiance_c, "population": population_c,
                },
            )
            system_db_id_c: int = sys_result_c.scalar_one()

            db.execute(
                text("""
                    INSERT INTO pp_system_snapshots
                        (system_id, ingestion_run_id, snapshot_time,
                         spansh_updated_at,
                         power, power_state, control_progress,
                         reinforcement, undermining,
                         powers_list, conflict_progress)
                    VALUES
                        (:system_id, :run_id, :now,
                         :spansh_updated_at,
                         :power, :power_state, :control_progress,
                         :reinforcement, :undermining,
                         :powers_list, :conflict_progress)
                """),
                {
                    "system_id":          system_db_id_c,
                    "run_id":             run_id,
                    "now":                datetime.utcnow(),
                    "spansh_updated_at":  spansh_updated_at_c,
                    "power":              None,           # no single controller
                    "power_state":        "Contested",    # our internal label
                    "control_progress":   control_progress_c,
                    "reinforcement":      reinforcement_c,
                    "undermining":        undermining_c,
                    "powers_list":        powers_list_c,
                    "conflict_progress":  conflict_progress_c,
                },
            )

            records_processed += 1
            contested_count   += 1
            if records_processed % BATCH_COMMIT_SIZE == 0:
                db.commit()

        db.commit()
        logger.info("  Finished Contested pass: %d systems stored", contested_count)

        # Final update
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
        logger.info(
            "Spansh PP ingest complete: %d total systems across %d powers + contested pass (run_id=%d)",
            records_processed, len(ALL_POWERS), run_id,
        )

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
