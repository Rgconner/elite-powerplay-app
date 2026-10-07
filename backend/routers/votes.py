"""Community target voting — current-state, not an event log.

See models.py's TargetVote docstring for why this is a separate table from
OodaDecision. Deliberately public, no auth — same posture as decisions.py.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import TargetVote
from models.schemas import TargetVoteCount, TargetVoteCreate, TargetVoteOut
from services.decay import current_cycle_start

router = APIRouter(prefix="/votes", tags=["votes"])


@router.post("", response_model=TargetVoteOut, status_code=201)
def cast_vote(vote: TargetVoteCreate, db: Session = Depends(get_db)):
    cycle_start = current_cycle_start()

    existing = (
        db.query(TargetVote)
        .filter(
            TargetVote.session_id == vote.session_id,
            TargetVote.system_id64 == vote.system_id64,
            TargetVote.signal_type == vote.signal_type,
            TargetVote.cycle_start == cycle_start,
        )
        .first()
    )
    if existing is not None:
        # Same voter, same system, same cycle -- idempotent re-vote, not a
        # duplicate. Nothing to change; voted_at intentionally NOT bumped,
        # so it still reflects when they first backed this target.
        return existing

    row = TargetVote(
        session_id=vote.session_id,
        power=vote.power,
        system_id64=vote.system_id64,
        signal_type=vote.signal_type,
        cycle_start=cycle_start,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("", status_code=204)
def retract_vote(
    session_id: str,
    system_id64: int,
    signal_type: str,
    db: Session = Depends(get_db),
):
    cycle_start = current_cycle_start()
    db.query(TargetVote).filter(
        TargetVote.session_id == session_id,
        TargetVote.system_id64 == system_id64,
        TargetVote.signal_type == signal_type,
        TargetVote.cycle_start == cycle_start,
    ).delete()
    db.commit()


@router.get("/aggregate", response_model=List[TargetVoteCount])
def vote_counts(power: str, signal_type: str, db: Session = Depends(get_db)):
    """Current-cycle vote counts per system for a power — the "N people are
    working this system" tally. Prior cycles are excluded by the
    cycle_start filter, not deleted (see models.py)."""
    cycle_start = current_cycle_start()
    rows = (
        db.query(TargetVote.system_id64, func.count(TargetVote.id).label("vote_count"))
        .filter(
            TargetVote.power == power,
            TargetVote.signal_type == signal_type,
            TargetVote.cycle_start == cycle_start,
        )
        .group_by(TargetVote.system_id64)
        .order_by(func.count(TargetVote.id).desc())
        .all()
    )
    return [
        TargetVoteCount(system_id64=r.system_id64, signal_type=signal_type, vote_count=r.vote_count)
        for r in rows
    ]
