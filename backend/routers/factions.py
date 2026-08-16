"""Factions router — read-only public endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import Faction, FactionPresence, PPSnapshot, System
from models.schemas import (
    FactionListItem,
    FactionSystemEntry,
    PaginatedFactions,
    PowersList,
    RecommendationsResponse,
)
from services.scoring import compute_recommendations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/factions", tags=["factions"])


# ---------------------------------------------------------------------------
# GET /api/factions  — paginated list
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedFactions)
def list_factions(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
) -> PaginatedFactions:
    """Return a paginated list of all factions with their system counts."""
    try:
        # Count distinct systems per faction via a subquery
        system_count_sub = (
            db.query(
                FactionPresence.faction_id,
                func.count(func.distinct(FactionPresence.system_id)).label("system_count"),
            )
            .group_by(FactionPresence.faction_id)
            .subquery()
        )

        base_query = db.query(
            Faction,
            func.coalesce(system_count_sub.c.system_count, 0).label("system_count"),
        ).outerjoin(system_count_sub, Faction.id == system_count_sub.c.faction_id)

        total: int = base_query.count()
        offset = (page - 1) * limit
        rows = base_query.order_by(Faction.name).offset(offset).limit(limit).all()

        items = [
            FactionListItem(
                id=faction.id,
                name=faction.name,
                allegiance=faction.allegiance,
                government=faction.government,
                system_count=int(cnt),
            )
            for faction, cnt in rows
        ]
        return PaginatedFactions(total=total, page=page, limit=limit, items=items)
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_factions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/factions/powers  — distinct PP powers present in snapshots
# ---------------------------------------------------------------------------


@router.get("/powers", response_model=PowersList)
def get_powers(db: Session = Depends(get_db)) -> PowersList:
    """Return the distinct set of pp_power values that exist in pp_snapshots."""
    try:
        rows = (
            db.query(PPSnapshot.pp_power)
            .filter(PPSnapshot.pp_power.isnot(None))
            .distinct()
            .order_by(PPSnapshot.pp_power)
            .all()
        )
        return PowersList(powers=[r.pp_power for r in rows])
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_powers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/factions/search  — name search (must be before /{name} route)
# ---------------------------------------------------------------------------


@router.get("/search", response_model=list[FactionListItem])
def search_factions(
    q: str = Query(default="", min_length=1),
    db: Session = Depends(get_db),
) -> list[FactionListItem]:
    """Case-insensitive substring search over faction names (max 20 results)."""
    try:
        system_count_sub = (
            db.query(
                FactionPresence.faction_id,
                func.count(func.distinct(FactionPresence.system_id)).label("system_count"),
            )
            .group_by(FactionPresence.faction_id)
            .subquery()
        )

        rows = (
            db.query(
                Faction,
                func.coalesce(system_count_sub.c.system_count, 0).label("system_count"),
            )
            .outerjoin(system_count_sub, Faction.id == system_count_sub.c.faction_id)
            .filter(Faction.name.ilike(f"%{q}%"))
            .order_by(Faction.name)
            .limit(20)
            .all()
        )

        return [
            FactionListItem(
                id=faction.id,
                name=faction.name,
                allegiance=faction.allegiance,
                government=faction.government,
                system_count=int(cnt),
            )
            for faction, cnt in rows
        ]
    except HTTPException:
        raise
    except Exception:
        logger.exception("search_factions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/factions/{name}/systems  — systems for a faction with latest PP state
# ---------------------------------------------------------------------------


@router.get("/{name}/systems", response_model=list[FactionSystemEntry])
def get_faction_systems(
    name: str,
    center_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[FactionSystemEntry]:
    """
    Return all systems for a given faction, joined with the latest pp_snapshot
    per system using DISTINCT ON.  Optionally compute Euclidean distance from a
    center system when ``center_id`` (system_id64) is supplied.
    """
    try:
        # Resolve faction
        faction = db.query(Faction).filter(Faction.name == name).first()
        if faction is None:
            return []

        # Build a subquery: latest pp_snapshot per system (PostgreSQL DISTINCT ON)
        latest_pp_sql = text(
            """
            SELECT DISTINCT ON (system_id) system_id, pp_power, pp_state, influence
            FROM pp_snapshots
            ORDER BY system_id, snapshot_time DESC
            """
        )
        latest_pp_sub = db.execute(latest_pp_sql).mappings().all()
        # Build a lookup dict: systems.id → snapshot fields
        pp_by_system: dict[int, dict] = {
            row["system_id"]: {
                "pp_power": row["pp_power"],
                "pp_state": row["pp_state"],
                "influence": row["influence"],
            }
            for row in latest_pp_sub
        }

        # Query distinct (faction_id, system_id) presence rows for this faction
        presence_rows = (
            db.query(FactionPresence, System)
            .join(System, FactionPresence.system_id == System.id)
            .filter(FactionPresence.faction_id == faction.id)
            # Deduplicate: if a system appears in multiple runs, keep the one where
            # is_controlling=True if any, otherwise either is fine.  Use DISTINCT ON
            # via Python grouping (presence data is the same across runs for a system).
            .distinct(FactionPresence.system_id)
            .order_by(FactionPresence.system_id, FactionPresence.is_controlling.desc())
            .all()
        )

        # Optionally resolve center system coords
        cx: Optional[float] = None
        cy: Optional[float] = None
        cz: Optional[float] = None
        if center_id is not None:
            center_sys = (
                db.query(System).filter(System.system_id64 == center_id).first()
            )
            if center_sys is not None:
                cx, cy, cz = center_sys.x, center_sys.y, center_sys.z

        results: list[FactionSystemEntry] = []
        for presence, system in presence_rows:
            pp = pp_by_system.get(system.id, {})

            x = system.x or 0.0
            y = system.y or 0.0
            z = system.z or 0.0

            distance: Optional[float] = None
            if cx is not None and cy is not None and cz is not None:
                distance = ((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) ** 0.5

            results.append(
                FactionSystemEntry(
                    system_name=system.name,
                    system_id64=system.system_id64,
                    is_controlling=presence.is_controlling,
                    x=x,
                    y=y,
                    z=z,
                    pp_state=pp.get("pp_state"),
                    pp_power=pp.get("pp_power"),
                    influence=pp.get("influence"),
                    distance_from_center=distance,
                )
            )

        return results
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_faction_systems failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/factions/{name}/recommendations
# ---------------------------------------------------------------------------


@router.get("/{name}/recommendations", response_model=RecommendationsResponse)
def get_faction_recommendations(
    name: str,
    center_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    """Return rule-based fortify and expand recommendations for a faction."""
    try:
        result = compute_recommendations(name, center_id, db)
        return RecommendationsResponse(**result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_faction_recommendations failed")
        raise HTTPException(status_code=500, detail="Internal server error")
