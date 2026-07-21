"""
Spansh router — proxy and cached enrichment for Spansh system/body data.

Endpoints:
  POST /api/spansh/enrich/batch  — Accept { system_ids: number[] }, returns
                                   { system_id64: { has_platinum, has_boom } }
                                   using cached data (12-hour TTL) or fetching
                                   fresh from Spansh API as needed.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spansh", tags=["spansh"])

# ── Constants ─────────────────────────────────────────────────────────────────

SPANSH_SYSTEM_URL = "https://spansh.co.uk/api/system/{}"
SPANSH_BODY_URL   = "https://spansh.co.uk/api/body/{}"
CACHE_TTL_HOURS   = 12
BATCH_DELAY_MS    = 600   # 600 ms between individual fetch calls (rate limiting)

# ── Schemas ──────────────────────────────────────────────────────────────────


class BatchEnrichRequest(BaseModel):
    system_ids: list[int]


class EnrichResult(BaseModel):
    has_platinum: bool
    has_boom: bool


class BatchEnrichResponse(BaseModel):
    results: dict[int, EnrichResult]


class EnrichStatus(BaseModel):
    cached: int
    expired: int


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
    Check a single body (unwrapped) for a Platinum signal or Platinum in ring materials.
    
    Platinum is found in:
      1. signals array — each entry has a 'signals' list of { name, count } objects
      2. rings array — each ring may have a 'materials' dict or list with material names
    """
    try:
        # Check body signals
        signals = body.get("signals") or []
        for sig_group in signals:
            items = sig_group.get("signals") or []
            for item in items:
                if isinstance(item, dict) and item.get("name", "").lower() == "platinum":
                    return True

        # Check ring materials (platinum is commonly found in metallic rings)
        rings = body.get("rings") or []
        for ring in rings:
            mat = ring.get("materials", {})
            if isinstance(mat, dict):
                for mname in mat:
                    if "platinum" in mname.lower():
                        return True
            elif isinstance(mat, list):
                for m in mat:
                    mname = m.get("name", "") if isinstance(m, dict) else str(m)
                    if "platinum" in mname.lower():
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


async def _enrich_system(system_id64: int) -> tuple[bool, bool]:
    """
    Fetch Spansh system data and body data for a single system.
    Returns (has_platinum, has_boom).
    Rate-limited: caller should wait BATCH_DELAY_MS between calls.
    """
    system = await _fetch_system(system_id64)
    if system is None:
        return False, False

    has_boom = _check_system_for_boom(system)
    has_platinum = False

    # Check bodies in the system for planets with platinum signals
    bodies = system.get("bodies") or []
    for body_ref in bodies:
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

    return has_platinum, has_boom


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/enrich/batch", response_model=BatchEnrichResponse)
async def enrich_batch(
    body: BatchEnrichRequest,
    db: Session = Depends(get_db),
) -> BatchEnrichResponse:
    """
    Return cached PLAT/BOOM enrichment for one or more systems.
    If cache is missing or stale (>12h), fetch fresh from Spansh.
    Returns { system_id64: { has_platinum, has_boom } } for each requested ID.
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

    # --- Phase 1: Check cache ---
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    rows = db.execute(
        text("""
            SELECT system_id64, has_platinum, has_boom, cached_at
            FROM spansh_enrichment
            WHERE system_id64 = ANY(:ids)
        """),
        {"ids": unique_ids},
    ).mappings().all()

    cache_map: dict[int, dict] = {r["system_id64"]: r for r in rows}
    for sid in unique_ids:
        cached = cache_map.get(sid)
        if cached and cached["cached_at"] and cached["cached_at"].replace(tzinfo=timezone.utc) >= cutoff:
            # Cache hit — fresh enough
            results[sid] = EnrichResult(
                has_platinum=cached["has_platinum"],
                has_boom=cached["has_boom"],
            )
        else:
            need_fetch.append(sid)

    # --- Phase 2: Fetch missing/stale from Spansh ---
    if need_fetch:
        logger.info("Fetching Spansh enrichment for %d system(s)", len(need_fetch))
        for i, sid in enumerate(need_fetch):
            if i > 0:
                await asyncio.sleep(BATCH_DELAY_MS / 1000.0)  # rate limit

            has_platinum, has_boom = await _enrich_system(sid)

            # Upsert into cache
            db.execute(
                text("""
                    INSERT INTO spansh_enrichment (system_id64, has_platinum, has_boom, cached_at)
                    VALUES (:sid, :plat, :boom, NOW())
                    ON CONFLICT (system_id64) DO UPDATE SET
                        has_platinum = EXCLUDED.has_platinum,
                        has_boom = EXCLUDED.has_boom,
                        cached_at = EXCLUDED.cached_at
                """),
                {"sid": sid, "plat": has_platinum, "boom": has_boom},
            )
            db.commit()

            results[sid] = EnrichResult(has_platinum=has_platinum, has_boom=has_boom)

    return BatchEnrichResponse(results=results)


@router.get("/enrich/status", response_model=EnrichStatus)
def enrich_status(db: Session = Depends(get_db)) -> EnrichStatus:
    """Return cache hit/miss counts."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    total = db.execute(
        text("SELECT COUNT(*) FROM spansh_enrichment")
    ).scalar() or 0
    fresh = db.execute(
        text("SELECT COUNT(*) FROM spansh_enrichment WHERE cached_at >= :cutoff"),
        {"cutoff": cutoff},
    ).scalar() or 0
    return EnrichStatus(cached=fresh, expired=total - fresh)