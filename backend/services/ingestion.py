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
from services.decay import compute_cp_decay, current_cycle_start


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


# Spansh returns the odd 502/503 mid-ingest; without a retry one bad page
# failed the whole run (several runs a month).
RETRY_DELAYS = (5, 15, 30, 60)   # seconds before attempts 2..5


def _post_search(payload: dict, label: str, metrics: Optional[dict] = None) -> dict:
    """POST a Spansh systems/search query, retrying transient failures."""
    if metrics is not None:
        metrics["pages_fetched"] += 1
    for attempt in range(len(RETRY_DELAYS) + 1):
        if metrics is not None:
            metrics["api_calls"] += 1
        try:
            resp = requests.post(SPANSH_SEARCH_URL, json=payload, timeout=60)
            resp.raise_for_status()
            if metrics is not None:
                metrics["bytes_downloaded"] += len(resp.content)
            return resp.json()
        except Exception as exc:
            if metrics is not None:
                metrics["api_errors"] += 1
                metrics["errors"].append(f"[{label} attempt={attempt + 1}] {exc}"[:256])
            status = getattr(getattr(exc, "response", None), "status_code", None)
            transient = (
                isinstance(exc, (requests.ConnectionError, requests.Timeout))
                or status == 429
                or (status is not None and status >= 500)
            )
            if not transient or attempt == len(RETRY_DELAYS):
                raise
            delay = RETRY_DELAYS[attempt]
            logger.warning("Spansh %s failed (%s); retrying in %ds", label, exc, delay)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def _fetch_page_by_power(power: str, page: int, metrics: Optional[dict] = None) -> dict:
    """Fetch one page of systems for a power (controlling_power filter)."""
    payload = {
        "filters": {
            "controlling_power": {"value": [power], "comparison": "="}
        },
        "size": PAGE_SIZE,
        "page": page,
        "sort": [{"id64": {"direction": "asc"}}],
    }
    return _post_search(payload, f"page_by_power power={power!r} page={page}", metrics)


def _fetch_page_unoccupied(power: str, page: int, metrics: Optional[dict] = None) -> dict:
    """Fetch one page of Unoccupied systems that have *power* present.

    These are the 'contested' systems in PP2.0: power_state=Unoccupied but
    power[] contains 2+ entries, indicating multiple powers vying for control.
    Spansh does NOT have a 'Contested' state — the multi-power Unoccupied
    state IS the contested representation.
    """
    payload = {
        "filters": {
            "power_state": {"value": ["Unoccupied"], "comparison": "="},
            "power": {"value": [power], "comparison": "="},
        },
        "size": PAGE_SIZE,
        "page": page,
        "sort": [{"id64": {"direction": "asc"}}],
    }
    return _post_search(payload, f"page_unoccupied power={power!r} page={page}", metrics)


def _iter_power_systems(power: str, metrics: Optional[dict] = None):
    """Yield all system dicts for a given power, paging through the API."""
    page = 0
    total_reported = None

    while True:
        logger.debug("Fetching page %d for power '%s'", page, power)
        data = _fetch_page_by_power(power, page, metrics)

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


# Spansh's search caps any query at this many results: "count" tops out at
# 10,000 and pages past it fail.  A single Unoccupied query (~35,000 real
# systems) silently lost everything past the first 10k, so the pass is split
# per power, each of which is well under the cap.
SPANSH_MAX_RESULTS = 10_000


def _iter_unoccupied_systems(metrics: Optional[dict] = None):
    """Yield each multi-power Unoccupied system from the Spansh API once.

    PP2.0 contested systems appear as Unoccupied with a 'power' list containing
    2+ power names and a 'power_conflict_progress' array.  Queried per power
    (see SPANSH_MAX_RESULTS); a system with several powers shows up in several
    queries and is yielded only the first time.
    """
    seen: set[int] = set()

    for power in ALL_POWERS:
        page = 0
        total_reported = None

        while True:
            logger.debug("Fetching Unoccupied systems for '%s' page %d", power, page)
            data = _fetch_page_unoccupied(power, page, metrics)

            if total_reported is None:
                total_reported = data.get("count", 0)
                logger.info("  Unoccupied systems with '%s': %d reported by API", power, total_reported)
                if total_reported >= SPANSH_MAX_RESULTS:
                    logger.warning(
                        "  Unoccupied query for '%s' hit Spansh's %d-result cap; "
                        "systems past it are missing", power, SPANSH_MAX_RESULTS,
                    )

            results = data.get("results", [])
            if not results:
                break

            # Only yield systems with 2+ powers (the genuinely contested ones)
            # to avoid ingesting tens of thousands of irrelevant Unoccupied rows.
            for r in results:
                raw_p = r.get("power")
                sid = r.get("id64")
                if isinstance(raw_p, list) and len(raw_p) >= 2 and sid not in seen:
                    seen.add(sid)
                    yield r

            page += 1

            if (page * PAGE_SIZE) >= min(total_reported, SPANSH_MAX_RESULTS):
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
    started_at = datetime.utcnow()
    run = IngestionRun(
        source="spansh_pp",
        status="running",
        started_at=started_at,
        records_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id: int = run.id
    logger.info("Spansh PP ingest started via search API (run_id=%d)", run_id)

    records_processed = 0
    metrics: dict = {
        "api_calls": 0,
        "api_errors": 0,
        "errors": [],
        "bytes_downloaded": 0,
        "pages_fetched": 0,
    }

    try:
        for power in ALL_POWERS:
            logger.info("Ingesting power: %s", power)
            power_count = 0

            for system_obj in _iter_power_systems(power, metrics):
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

                # ── CP decay (derived from start-of-cycle progress, so it is
                # the same for every snapshot of this system in a cycle) ──
                cycle = current_cycle_start()
                cp_decay_val = compute_cp_decay(
                    power_state, control_progress, reinforcement, undermining
                )

                # Insert a fresh snapshot row (insert-only for history)
                db.execute(
                    text("""
                        INSERT INTO pp_system_snapshots
                            (system_id, ingestion_run_id, snapshot_time,
                             spansh_updated_at,
                             power, power_state, control_progress,
                             reinforcement, undermining,
                             powers_list, conflict_progress,
                             cp_decay, decay_cycle_start)
                        VALUES
                            (:system_id, :run_id, :now,
                             :spansh_updated_at,
                             :power, :power_state, :control_progress,
                             :reinforcement, :undermining,
                             :powers_list, :conflict_progress,
                             :cp_decay, :decay_cycle_start)
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
                        "cp_decay":           cp_decay_val,
                        "decay_cycle_start":  cycle,
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
        for system_obj in _iter_unoccupied_systems(metrics):
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

        # Final update — write telemetry alongside status
        completed_at = datetime.utcnow()
        error_detail: Optional[str] = "; ".join(metrics["errors"])[:2048] if metrics["errors"] else None
        db.execute(
            text("""
                UPDATE ingestion_runs
                SET status = 'completed',
                    completed_at = :now,
                    records_processed = :count,
                    duration_seconds = :duration,
                    api_calls_made = :api_calls,
                    api_errors = :api_errors,
                    error_count = :error_count,
                    error_detail = :error_detail,
                    bytes_downloaded = :bytes_downloaded,
                    pages_fetched = :pages_fetched
                WHERE id = :run_id
            """),
            {
                "now": completed_at,
                "count": records_processed,
                "duration": (completed_at - started_at).total_seconds(),
                "api_calls": metrics["api_calls"],
                "api_errors": metrics["api_errors"],
                "error_count": metrics["api_errors"],
                "error_detail": error_detail,
                "bytes_downloaded": metrics["bytes_downloaded"],
                "pages_fetched": metrics["pages_fetched"],
                "run_id": run_id,
            },
        )
        db.commit()
        db.refresh(run)
        logger.info(
            "Spansh PP ingest complete: %d total systems across %d powers + contested pass "
            "(run_id=%d, duration=%.1fs, api_calls=%d, pages=%d, bytes=%d, api_errors=%d)",
            records_processed, len(ALL_POWERS), run_id,
            (completed_at - started_at).total_seconds(),
            metrics["api_calls"], metrics["pages_fetched"],
            metrics["bytes_downloaded"], metrics["api_errors"],
        )

    except Exception:
        logger.exception("Spansh PP ingest failed (run_id=%d)", run_id)
        try:
            completed_at = datetime.utcnow()
            error_detail = "; ".join(metrics["errors"])[:2048] if metrics["errors"] else None
            db.execute(
                text("""
                    UPDATE ingestion_runs
                    SET status = 'failed',
                        completed_at = :now,
                        records_processed = :count,
                        duration_seconds = :duration,
                        api_calls_made = :api_calls,
                        api_errors = :api_errors,
                        error_count = :error_count,
                        error_detail = :error_detail,
                        bytes_downloaded = :bytes_downloaded,
                        pages_fetched = :pages_fetched
                    WHERE id = :id
                """),
                {
                    "now": completed_at,
                    "count": records_processed,
                    "duration": (completed_at - started_at).total_seconds(),
                    "api_calls": metrics["api_calls"],
                    "api_errors": metrics["api_errors"],
                    "error_count": metrics["api_errors"],
                    "error_detail": error_detail,
                    "bytes_downloaded": metrics["bytes_downloaded"],
                    "pages_fetched": metrics["pages_fetched"],
                    "id": run_id,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
        raise

    return run
