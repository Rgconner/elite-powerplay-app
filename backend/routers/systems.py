"""Systems router — read-only public endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import PPSnapshot, System
from models.schemas import SystemHistoryPoint, SystemSearchResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/systems", tags=["systems"])


# ---------------------------------------------------------------------------
# GET /api/systems/search  — system name search
# ---------------------------------------------------------------------------


@router.get("/search", response_model=list[SystemSearchResult])
def search_systems(
    q: str = Query(default="", min_length=1),
    db: Session = Depends(get_db),
) -> list[SystemSearchResult]:
    """Case-insensitive substring search over system names (max 20 results)."""
    try:
        rows = (
            db.query(System)
            .filter(System.name.ilike(f"%{q}%"))
            .order_by(System.name)
            .limit(20)
            .all()
        )
        return [
            SystemSearchResult(
                system_id64=s.system_id64,
                name=s.name,
                x=s.x,
                y=s.y,
                z=s.z,
            )
            for s in rows
        ]
    except HTTPException:
        raise
    except Exception:
        logger.exception("search_systems failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/systems/{system_id64}/history  — PP snapshots over time
# ---------------------------------------------------------------------------


@router.get("/{system_id64}/history", response_model=list[SystemHistoryPoint])
def get_system_history(
    system_id64: int,
    db: Session = Depends(get_db),
) -> list[SystemHistoryPoint]:
    """Return all pp_snapshots for the given system, ordered chronologically."""
    try:
        system = db.query(System).filter(System.system_id64 == system_id64).first()
        if system is None:
            return []

        rows = (
            db.query(PPSnapshot)
            .filter(PPSnapshot.system_id == system.id)
            .order_by(PPSnapshot.snapshot_time.asc())
            .all()
        )
        return [
            SystemHistoryPoint(
                snapshot_time=r.snapshot_time,
                pp_state=r.pp_state,
                pp_power=r.pp_power,
                influence=r.influence,
            )
            for r in rows
        ]
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_system_history failed")
        raise HTTPException(status_code=500, detail="Internal server error")
