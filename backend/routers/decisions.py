"""OODA decision recording — the core telemetry layer.

Deliberately public, no auth: this is player behavioral telemetry from an
unauthenticated public tool (see README — "read views are public"), not an
admin action. Records unconditionally regardless of AI availability; see
services/ai_health.py for why ai_available is stamped server-side rather
than trusted from the client.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import OodaDecision
from models.schemas import OodaDecisionCreate, OodaDecisionOut
from services.ai_health import ai_is_available

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post("", response_model=OodaDecisionOut, status_code=201)
def record_decision(decision: OodaDecisionCreate, db: Session = Depends(get_db)):
    row = OodaDecision(
        **decision.model_dump(),
        ai_available=ai_is_available(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
