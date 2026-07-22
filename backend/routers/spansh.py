"""
Spansh router — proxy and cached enrichment for Spansh system/body data.

Endpoints:
  POST /api/spansh/enrich/batch  — Accept { system_ids: number[], force_refresh? }, returns
                                   { system_id64: { has_platinum, has_boom, has_pristine } }
                                   using persistent cache (fetch on first access) or
                                   fetching fresh from Spansh API as needed.
  DELETE /api/spansh/enrich/cache — Clear all cached enrichment data (admin-only).
  GET   /api/spansh/enrich/status — Return cache stats.
  POST  /api/spansh/enrich/validate — Validate cached entries against live Spansh data (admin-only).
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.session import get_db
from routers.deps import AdminUserDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spansh", tags=["spansh"])

# ── Constants ─────────────────────────────────────────────────────────────────

SPANSH_SYSTEM_URL        = "https://spansh.co.uk/api/system/{}"
SPANSH_SYSTEM_DUMP_URL   = "https://spansh.co.uk/api/dump/{}"
SPANSH_BODY_URL          = "https://spansh.co.uk/api/body/{}"
SPANSH_BODIES_SEARCH_URL = "https://spansh.co.uk/api/bodies/search"
BATCH_DELAY_MS           = 600  # 600 ms between individual fetch calls (rate limiting)

# ── Schemas ──────────────────────────────────────────────────────────────────


class BatchEnrichRequest(BaseModel):
    system_ids: list[int]
    force_refresh: bool = False  # bypass cache and re-fetch from Spansh


class EnrichResult(BaseModel):
    has_platinum: bool
    has_boom: bool
    has_pristine: bool


class BatchEnrichResponse(BaseModel):
    results: dict[int, EnrichResult]


class EnrichStatus(BaseModel):
    total_cached: int


class ValidateMismatch(BaseModel):
    system_id64: int
    system_name: str | None = None
    field: str
    cached: bool
    live: bool


class ValidateResponse(BaseModel):
    total_checked: int
    mismatches_found: int
    mismatches: list[ValidateMismatch]


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fetch_system(system_id64: int) -> dict | None:
    """Fetch system data from Spansh API, returns parsed JSON or None.

    The Spansh system API wraps the record in a {"record": {...}} envelope,
    so we unwrap it before returning.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SPANSH_SYSTEM_URL.format(system_id64))
            if resp.status_code == 200:
                raw = resp.json()
                # Unwrap the record envelope that Spansh uses
                return raw.get("record", raw)
            logger.warning("Spansh system %d returned %d", system_id64, resp.status_code)
            return None
    except Exception as e:
        logger.error("Error fetching Spansh system %d: %s", system_id64, e)
        return None


async def _fetch_body(body_id64: int) -> dict | None:
    """Fetch body data from Spansh API, returns parsed JSON or None.

    The Spansh body API also wraps the record in a {"record": {...}} envelope.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SPANSH_BODY_URL.format(body_id64))
            if resp.status_code == 200:
                raw = resp.json()
                # Unwrap the record envelope that Spansh uses
                return raw.get("record", raw)
            return None
    except Exception as e:
        logger.error("Error fetching Spansh body %d: %s", body_id64, e)
        return None


def _check_body_for_platinum(body: dict) -> bool:
    """
    Check a single body (unwrapped) for a Platinum signal.

    Platinum is found in the ring signals:
      rings[].signals[]  →  each entry is a dict with { name: str, count: int }

    Confirmed via Spansh API (July 2026):
      GET /api/body/{id64}  →  body.rings[].signals[]
      POST /api/bodies/search  →  result.rings[].signals[]

    Note: body records do NOT have a top-level "signals" field, and ring
    records store signals in "signals" (not "materials").  The previous
    code checked body.get("signals") and ring.get("materials") which
    were both empty — causing all systems to report has_platinum=false.
    """
    try:
        rings = body.get("rings") or []
        for ring in rings:
            ring_signals = ring.get("signals") or []
            for sig in ring_signals:
                if isinstance(sig, dict) and sig.get("name", "").lower() == "platinum":
                    return True
    except Exception:
        pass
    return False


def _check_system_for_boom(system: dict) -> bool:
    """
    Check a system response for BOOM active state in any minor faction.
    The system JSON has a 'minor_faction_presences' array where each entry
    has an 'active_states' array.
    """
    try:
        factions = system.get("minor_faction_presences") or []
        for faction in factions:
            states = faction.get("active_states") or []
            for state in states:
                if isinstance(state, str) and state.upper() == "BOOM":
                    return True
                if isinstance(state, dict) and state.get("name", "").upper() == "BOOM":
                    return True
    except Exception:
        pass
    return False


def _check_system_for_pristine(system: dict) -> bool:
    """
    Check a system dump for Pristine reserve level.

    The Spansh dump API (https://spansh.co.uk/api/dump/{id64}) returns
    system data with bodies.  Each body may have a 'reserve_level' field
    (e.g. "Pristine", "Major", "Common", "Low", "Depleted").

    We check both:
      1. Top-level 'reserve_level' on the system/dump record itself
      2. 'reserve_level' on individual bodies (rings/belts have their own)
    """
    try:
        # Check top-level reserve_level (some API responses include it)
        top_reserve = system.get("reserve_level") or system.get("reserve")
        if isinstance(top_reserve, str) and top_reserve.lower() == "pristine":
            return True

        # Check per-body reserve_level
        bodies = system.get("bodies") or []
        for body in bodies:
            if not isinstance(body, dict):
                continue
            reserve = body.get("reserve_level") or body.get("reserve")
            if isinstance(reserve, str) and reserve.lower() == "pristine":
                return True
    except Exception:
        pass
    return False


async def _fetch_bodies_by_system_name(system_name: str) -> list[dict] | None:
    """Fetch all bodies for a system via the Spansh bodies/search API.

    This endpoint returns complete body data (including rings and materials)
    in a single call — no need to fetch individual bodies. This is both
    faster and more reliable than the system→body fetch chain.

    Returns a list of body dicts, or None if the request failed.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                SPANSH_BODIES_SEARCH_URL,
                json={
                    "filters": {
                        "system_name": {
                            "value": [system_name],
                            "comparison": "=",
                        }
                    },
                    "size": 100,  # max bodies to return
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            logger.warning(
                "Spansh bodies/search for '%s' returned %d",
                system_name, resp.status_code,
            )
            return None
    except Exception as e:
        logger.error("Error fetching bodies for system '%s': %s", system_name, e)
        return None


def _check_bodies_for_platinum(bodies: list[dict]) -> bool:
    """Check a list of body dicts (from bodies/search) for platinum.

    The bodies/search API returns flat body data with rings and signals
    directly — no 'record' wrapper, no need for per-body fetches.
    """
    for body in bodies:
        if not isinstance(body, dict):
            continue
        if _check_body_for_platinum(body):
            return True
    return False


async def _enrich_system(system_id64: int, system_name: str | None = None) -> tuple[bool, bool, bool]:
    """
    Fetch Spansh enrichment data for a single system.
    Returns (has_platinum, has_boom, has_pristine).
    Rate-limited: caller should wait BATCH_DELAY_MS between calls.

    Strategy (primary → fallback):
      1. bodies/search API by system name — single call, complete body data
         including rings/materials. Most reliable for platinum detection.
      2. system/{id} → per-body fetch chain — fallback when name is unknown
         or bodies/search fails. Slower but works with id64 only.

    BOOM is always checked from the system/{id} response (minor faction data
    is not available via bodies/search).

    PRISTINE is checked from the system dump API for reserve_level data.
    """
    # Always fetch the system record for BOOM detection
    system = await _fetch_system(system_id64)
    if system is None:
        return False, False, False

    has_boom = _check_system_for_boom(system)
    has_platinum = False

    # ── Primary: bodies/search API (if we have the system name) ──────────────
    if system_name:
        bodies = await _fetch_bodies_by_system_name(system_name)
        if bodies is not None:
            has_platinum = _check_bodies_for_platinum(bodies)
            if has_platinum:
                # Still need to check pristine from the dump API
                pass
            # If bodies/search returned results but no platinum, trust it.
            # Only fall through to the per-body chain if we got no results
            # at all (None = request failed; [] = system has no bodies).
            if len(bodies) > 0 and has_platinum:
                # Check pristine from dump, then return early
                dump_data = await _fetch_system_dump(system_id64)
                has_pristine = _check_system_for_pristine(dump_data) if dump_data else False
                return has_platinum, has_boom, has_pristine
            if len(bodies) > 0:
                # No platinum found; check pristine from dump
                dump_data = await _fetch_system_dump(system_id64)
                has_pristine = _check_system_for_pristine(dump_data) if dump_data else False
                return has_platinum, has_boom, has_pristine
            # Empty results — might be a name mismatch; try fallback below.

    # ── Fallback: system/{id} → per-body fetch chain ─────────────────────────
    body_refs = system.get("bodies") or []
    for body_ref in body_refs:
        if not isinstance(body_ref, dict):
            continue
        # Only check planets
        body_type = (body_ref.get("type") or "").lower()
        if "planet" not in body_type:
            continue
        body_id64 = body_ref.get("id64")
        if body_id64 is None:
            continue

        # Fetch the body detail and check for platinum
        await asyncio.sleep(0.05)  # small delay between body fetches
        body = await _fetch_body(body_id64)
        if body and _check_body_for_platinum(body):
            has_platinum = True
            break  # found platinum, no need to check more bodies

    # ── Check pristine from dump API ─────────────────────────────────────────
    dump_data = await _fetch_system_dump(system_id64)
    has_pristine = _check_system_for_pristine(dump_data) if dump_data else False

    return has_platinum, has_boom, has_pristine


async def _fetch_system_dump(system_id64: int) -> dict | None:
    """Fetch system dump data from Spansh dump API for reserve level info.

    The dump endpoint (https://spansh.co.uk/api/dump/{id64}) returns
    detailed system data including body reserve levels.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SPANSH_SYSTEM_DUMP_URL.format(system_id64))
            if resp.status_code == 200:
                raw = resp.json()
                return raw.get("record", raw)
            logger.warning("Spansh dump %d returned %d", system_id64, resp.status_code)
            return None
    except Exception as e:
        logger.error("Error fetching Spansh dump %d: %s", system_id64, e)
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/enrich/batch", response_model=BatchEnrichResponse)
async def enrich_batch(
    body: BatchEnrichRequest,
    db: Session = Depends(get_db),
) -> BatchEnrichResponse:
    """
    Return cached PLAT/BOOM/PRISTINE enrichment for one or more systems.
    If cache is missing, fetch fresh from Spansh. Existing cache is used
    as-is (no TTL expiry) — data persists until explicitly cleared.
    Returns { system_id64: { has_platinum, has_boom, has_pristine } }
    for each requested ID.

    Set force_refresh=true to bypass the cache and re-fetch from Spansh.
    This is useful after deploying detection fixes to invalidate
    stale cache entries.
    """
    ids = body.system_ids
    if not ids:
        return BatchEnrichResponse(results={})

    # Deduplicate and preserve order
    seen: set[int] = set()
    unique_ids: list[int] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            unique_ids.append(sid)

    results: dict[int, EnrichResult] = {}
    need_fetch: list[int] = []

    # --- Phase 1: Check cache (unless force_refresh) ---
    if body.force_refresh:
        need_fetch = unique_ids
    else:
        rows = db.execute(
            text("""
                SELECT system_id64, has_platinum, has_boom, has_pristine
                FROM spansh_enrichment
                WHERE system_id64 = ANY(:ids)
            """),
            {"ids": unique_ids},
        ).mappings().all()

        cache_map: dict[int, dict] = {r["system_id64"]: r for r in rows}
        for sid in unique_ids:
            cached = cache_map.get(sid)
            if cached is not None:
                # Cache hit — use persisted data regardless of age
                results[sid] = EnrichResult(
                    has_platinum=cached["has_platinum"],
                    has_boom=cached["has_boom"],
                    has_pristine=cached.get("has_pristine", False),
                )
            else:
                need_fetch.append(sid)

    # --- Phase 2: Fetch missing from Spansh (first-access) ---
    if need_fetch:
        logger.info("Fetching Spansh enrichment for %d system(s)", len(need_fetch))

        # Look up system names from pp_systems for the bodies/search API.
        # This enables the more reliable bodies/search enrichment path.
        name_rows = db.execute(
            text("""
                SELECT system_id64, name
                FROM pp_systems
                WHERE system_id64 = ANY(:ids)
            """),
            {"ids": need_fetch},
        ).mappings().all()
        name_map: dict[int, str] = {r["system_id64"]: r["name"] for r in name_rows}

        for i, sid in enumerate(need_fetch):
            if i > 0:
                await asyncio.sleep(BATCH_DELAY_MS / 1000.0)  # rate limit

            sys_name = name_map.get(sid)
            has_platinum, has_boom, has_pristine = await _enrich_system(sid, sys_name)

            # Upsert into cache (first-access persistence)
            db.execute(
                text("""
                    INSERT INTO spansh_enrichment (system_id64, has_platinum, has_boom, has_pristine, cached_at)
                    VALUES (:sid, :plat, :boom, :prist, NOW())
                    ON CONFLICT (system_id64) DO UPDATE SET
                        has_platinum = EXCLUDED.has_platinum,
                        has_boom = EXCLUDED.has_boom,
                        has_pristine = EXCLUDED.has_pristine,
                        cached_at = EXCLUDED.cached_at
                """),
                {"sid": sid, "plat": has_platinum, "boom": has_boom, "prist": has_pristine},
            )
            db.commit()

            results[sid] = EnrichResult(
                has_platinum=has_platinum, has_boom=has_boom, has_pristine=has_pristine,
            )

    return BatchEnrichResponse(results=results)


@router.delete("/enrich/cache")
def clear_enrich_cache(
    db: Session = Depends(get_db),
    _admin: dict = Depends(AdminUserDep),
) -> dict:
    """Clear all cached Spansh enrichment data.  Admin-only.

    After clearing, the next batch request will re-fetch fresh data from
    Spansh on first access for each system.
    """
    result = db.execute(text("DELETE FROM spansh_enrichment"))
    db.commit()
    deleted = result.rowcount
    logger.info("Cleared %d rows from spansh_enrichment cache", deleted)
    return {"deleted": deleted}


@router.get("/enrich/status", response_model=EnrichStatus)
def enrich_status(db: Session = Depends(get_db)) -> EnrichStatus:
    """Return total cached enrichment count."""
    total = db.execute(
        text("SELECT COUNT(*) FROM spansh_enrichment")
    ).scalar() or 0
    return EnrichStatus(total_cached=total)


@router.post("/enrich/validate", response_model=ValidateResponse)
async def validate_enrich_cache(
    db: Session = Depends(get_db),
    _admin: dict = Depends(AdminUserDep),
) -> ValidateResponse:
    """
    Validate cached enrichment entries against live Spansh data.
    For each cached entry, re-fetches from Spansh and compares results.
    Mismatches are auto-corrected in the database.
    """
    rows = db.execute(
        text("SELECT system_id64, has_platinum, has_boom, has_pristine FROM spansh_enrichment")
    ).mappings().all()

    mismatches: list[ValidateMismatch] = []
    total_checked = 0

    # Look up system names for display
    all_ids = [r["system_id64"] for r in rows]
    name_map: dict[int, str] = {}
    if all_ids:
        name_rows = db.execute(
            text("SELECT system_id64, name FROM pp_systems WHERE system_id64 = ANY(:ids)"),
            {"ids": all_ids},
        ).mappings().all()
        name_map = {r["system_id64"]: r["name"] for r in name_rows}

    for i, row in enumerate(rows):
        if i > 0:
            await asyncio.sleep(BATCH_DELAY_MS / 1000.0)  # rate limit

        sid = row["system_id64"]
        sys_name = name_map.get(sid)
        total_checked += 1

        live_plat, live_boom, live_prist = await _enrich_system(sid, sys_name)
        cached_plat = row["has_platinum"]
        cached_boom = row["has_boom"]
        cached_prist = row.get("has_pristine", False)

        has_mismatch = False

        if cached_plat != live_plat:
            mismatches.append(ValidateMismatch(
                system_id64=sid, system_name=sys_name,
                field="has_platinum", cached=cached_plat, live=live_plat,
            ))
            has_mismatch = True

        if cached_boom != live_boom:
            mismatches.append(ValidateMismatch(
                system_id64=sid, system_name=sys_name,
                field="has_boom", cached=cached_boom, live=live_boom,
            ))
            has_mismatch = True

        if cached_prist != live_prist:
            mismatches.append(ValidateMismatch(
                system_id64=sid, system_name=sys_name,
                field="has_pristine", cached=cached_prist, live=live_prist,
            ))
            has_mismatch = True

        # Auto-correct mismatches
        if has_mismatch:
            db.execute(
                text("""
                    UPDATE spansh_enrichment
                    SET has_platinum = :plat, has_boom = :boom, has_pristine = :prist, cached_at = NOW()
                    WHERE system_id64 = :sid
                """),
                {"sid": sid, "plat": live_plat, "boom": live_boom, "prist": live_prist},
            )
            db.commit()
            logger.info("Corrected enrichment for system %d (%s)", sid, sys_name)

    logger.info(
        "Enrichment validation complete: %d checked, %d mismatches found",
        total_checked, len(mismatches),
    )
    return ValidateResponse(
        total_checked=total_checked,
        mismatches_found=len(mismatches),
        mismatches=mismatches,
    )