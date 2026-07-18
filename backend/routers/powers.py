"""Powers router — read-only public endpoints for Power Play data."""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import PPSystem, PPSystemSnapshot
from models.schemas import (
    PPSystemEntry,
    PowersList,
    RecommendationsResponse,
    SystemHistoryPoint,
    SystemSearchResult,
    TargetAnalysisItem,
    TargetAnalysisRequest,
    TargetAnalysisResponse,
)
from services.scoring import compute_recommendations

router = APIRouter(prefix="/powers", tags=["powers"])


# ---------------------------------------------------------------------------
# GET /api/powers  — list all known powers from latest snapshots
# ---------------------------------------------------------------------------


@router.get("", response_model=PowersList)
def list_powers(db: Session = Depends(get_db)) -> PowersList:
    """Return all distinct power names present in the latest snapshot data."""
    rows = db.execute(
        text("""
            SELECT DISTINCT power
            FROM pp_system_snapshots
            WHERE power IS NOT NULL
            ORDER BY power
        """)
    ).all()
    return PowersList(powers=[r.power for r in rows])


# ---------------------------------------------------------------------------
# GET /api/powers/search  — autocomplete for power names
# ---------------------------------------------------------------------------


@router.get("/search", response_model=PowersList)
def search_powers(
    q: str = Query(default="", min_length=1),
    db: Session = Depends(get_db),
) -> PowersList:
    """Case-insensitive substring search over power names."""
    rows = db.execute(
        text("""
            SELECT DISTINCT power
            FROM pp_system_snapshots
            WHERE power ILIKE :q
            ORDER BY power
            LIMIT 20
        """),
        {"q": f"%{q}%"},
    ).all()
    return PowersList(powers=[r.power for r in rows])


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/systems  — all systems for a power
# ---------------------------------------------------------------------------


@router.get("/{name}/systems", response_model=list[PPSystemEntry])
def get_power_systems(
    name: str,
    center_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PPSystemEntry]:
    """
    Return all systems currently under the given Power's influence,
    enriched with their latest PP snapshot.  Optionally compute distance
    from a center system when center_id (system_id64) is supplied.
    """
    # Latest snapshot per system
    latest_sql = text("""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress, snapshot_time
        FROM pp_system_snapshots
        WHERE power = :power
        ORDER BY system_id, snapshot_time DESC
    """)
    snap_rows = db.execute(latest_sql, {"power": name}).mappings().all()

    if not snap_rows:
        return []

    system_ids = [r["system_id"] for r in snap_rows]
    snap_by_id = {r["system_id"]: r for r in snap_rows}

    systems = db.query(PPSystem).filter(PPSystem.id.in_(system_ids)).all()
    sys_by_id = {s.id: s for s in systems}

    # Resolve center coords
    cx: Optional[float] = None
    cy: Optional[float] = None
    cz: Optional[float] = None
    if center_id is not None:
        center_sys = db.query(PPSystem).filter(PPSystem.system_id64 == center_id).first()
        if center_sys:
            cx, cy, cz = center_sys.x, center_sys.y, center_sys.z

    results: list[PPSystemEntry] = []
    for sid, snap in snap_by_id.items():
        system = sys_by_id.get(sid)
        if system is None:
            continue

        x = system.x or 0.0
        y = system.y or 0.0
        z = system.z or 0.0

        distance: Optional[float] = None
        if cx is not None and cy is not None and cz is not None:
            distance = math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)

        rein = snap["reinforcement"]
        under = snap["undermining"]
        undermine_ratio: Optional[float] = None
        if rein and rein > 0 and under is not None:
            undermine_ratio = under / rein

        results.append(PPSystemEntry(
            system_id64=system.system_id64,
            name=system.name,
            x=x, y=y, z=z,
            allegiance=system.allegiance,
            population=system.population,
            power=snap["power"],
            power_state=snap["power_state"],
            reinforcement=rein,
            undermining=under,
            control_progress=snap["control_progress"],
            snapshot_time=snap["snapshot_time"],
            distance_from_center=distance,
            undermine_ratio=undermine_ratio,
        ))

    return results


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/recommendations
# ---------------------------------------------------------------------------


@router.get("/{name}/recommendations", response_model=RecommendationsResponse)
def get_power_recommendations(
    name: str,
    center_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    """Return fortify and expand recommendations for a Power."""
    result = compute_recommendations(name, center_id, db)
    return RecommendationsResponse(**result)


# ---------------------------------------------------------------------------
# POST /api/powers/target-analysis
# ---------------------------------------------------------------------------

# Score constants (mirroring scoring.py bands so the UI colours align)
_TA_SCORE_STRONGHOLD   = 1000.0   # Stronghold — best undermine target
_TA_SCORE_FORTIFIED    =  600.0   # Fortified
_TA_SCORE_EXPLOITED    =  200.0   # Exploited — low value but still counts
_TA_DIST_MAX_LY        =   30.0   # beyond this distance proximity bonus = 0
_TA_PROGRESS_BONUS_MAX =  300.0   # extra points when progress is near 0
_TA_PROX_BONUS_MAX     =  150.0   # extra points when attacker is ≤5 LY away

CYCLE_DAYS = 7.0


def _dist3(ax: float, ay: float, az: float,
           bx: float, by: float, bz: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _estimate_days_to_downgrade(
    progress: float,
    reinforcement: int,
    undermining: int,
) -> Optional[float]:
    """Estimate days until progress hits 0.0 (state downgrade) at current rate."""
    if progress <= 0.0:
        return 0.0
    net = reinforcement - undermining          # negative = losing ground
    if net >= 0:
        return None                            # winning — no downgrade imminent
    deficit = abs(net)
    total_cap = max(reinforcement, deficit, 1) * 1.5
    daily_loss = (deficit / total_cap) / CYCLE_DAYS
    if daily_loss <= 0:
        return None
    return progress / daily_loss


@router.post("/target-analysis", response_model=TargetAnalysisResponse)
def target_analysis(
    body: TargetAnalysisRequest,
    db: Session = Depends(get_db),
) -> TargetAnalysisResponse:
    """
    Score enemy systems for undermining priority.

    Scoring model:
      Base score by state:  Stronghold=1000  Fortified=600  Exploited=200
      Progress bonus:       +300 × (1 - progress)  — closer to 0 = more bonus
      Proximity bonus:      +150 × max(0, 1 - dist/30)  — closer to attacker = more
      State-value bonus:    Stronghold that is also close to downgrade is HIGHEST pri
    Only Stronghold / Fortified / Exploited systems are included (not Unoccupied).
    """
    attacker = body.attacker_power
    targets  = body.target_powers

    # ── 1. Get attacker's system coords ──────────────────────────────────────
    attacker_snap_rows = db.execute(text("""
        SELECT DISTINCT ON (system_id)
               system_id, power
        FROM pp_system_snapshots
        WHERE power = :power
        ORDER BY system_id, snapshot_time DESC
    """), {"power": attacker}).mappings().all()

    attacker_sys_ids = [r["system_id"] for r in attacker_snap_rows]
    attacker_systems = db.query(PPSystem).filter(
        PPSystem.id.in_(attacker_sys_ids)
    ).all() if attacker_sys_ids else []
    attacker_coords = [
        (s.x or 0.0, s.y or 0.0, s.z or 0.0) for s in attacker_systems
    ]

    # ── 2. Get latest snapshots for all target powers ─────────────────────────
    if not targets:
        return TargetAnalysisResponse(
            targets=[], attacker_power=attacker, target_powers=targets
        )

    target_snap_rows = db.execute(text("""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress
        FROM pp_system_snapshots
        WHERE power = ANY(:powers)
        ORDER BY system_id, snapshot_time DESC
    """), {"powers": targets}).mappings().all()

    if not target_snap_rows:
        return TargetAnalysisResponse(
            targets=[], attacker_power=attacker, target_powers=targets
        )

    target_sys_ids = [r["system_id"] for r in target_snap_rows]
    target_systems_orm = db.query(PPSystem).filter(
        PPSystem.id.in_(target_sys_ids)
    ).all()
    sys_by_id = {s.id: s for s in target_systems_orm}
    snap_by_id = {r["system_id"]: r for r in target_snap_rows}

    # ── 3. Get progress trends for all target systems ─────────────────────────
    trend_rows = db.execute(text("""
        SELECT system_id,
               control_progress,
               snapshot_time,
               ROW_NUMBER() OVER (
                   PARTITION BY system_id
                   ORDER BY snapshot_time DESC
               ) AS rn
        FROM pp_system_snapshots
        WHERE system_id = ANY(:ids)
          AND control_progress IS NOT NULL
        ORDER BY system_id, snapshot_time DESC
    """), {"ids": target_sys_ids}).mappings().all()

    # Build dict: system_id -> list of (progress, time) newest-first, max 3
    trend_map: dict[int, list] = {}
    for row in trend_rows:
        sid = row["system_id"]
        if row["rn"] <= 3:
            trend_map.setdefault(sid, []).append(
                (row["control_progress"], row["snapshot_time"])
            )

    def _trend(sid: int) -> str:
        pts = trend_map.get(sid, [])
        if len(pts) < 2:
            return "unknown"
        p_new, p_old = pts[0][0], pts[1][0]
        if p_new < p_old - 0.01:
            return "worsening"
        if p_new > p_old + 0.01:
            return "improving"
        return "stable"

    # ── 4. Score each target system ───────────────────────────────────────────
    items: list[TargetAnalysisItem] = []

    for sid, snap in snap_by_id.items():
        system = sys_by_id.get(sid)
        if system is None:
            continue

        power_state = snap["power_state"]
        if power_state not in ("Stronghold", "Fortified", "Exploited"):
            continue   # skip Unoccupied — nothing to undermine

        progress   = snap["control_progress"] or 0.5
        rein       = snap["reinforcement"] or 0
        under      = snap["undermining"]   or 0
        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0

        # Base score by state tier
        base = (
            _TA_SCORE_STRONGHOLD if power_state == "Stronghold"
            else _TA_SCORE_FORTIFIED  if power_state == "Fortified"
            else _TA_SCORE_EXPLOITED
        )

        # Progress bonus: the closer to 0 the more vulnerable
        # progress ≤0 → full bonus; progress ≥1 → no bonus
        prog_clamped = max(0.0, min(1.0, progress))
        progress_bonus = _TA_PROGRESS_BONUS_MAX * (1.0 - prog_clamped)

        # Proximity bonus
        dist_from_attacker: Optional[float] = None
        prox_bonus = 0.0
        if attacker_coords:
            dist_from_attacker = min(
                _dist3(sx, sy, sz, ax, ay, az)
                for ax, ay, az in attacker_coords
            )
            if dist_from_attacker <= _TA_DIST_MAX_LY:
                prox_bonus = _TA_PROX_BONUS_MAX * max(
                    0.0, 1.0 - dist_from_attacker / _TA_DIST_MAX_LY
                )

        score = round(base + progress_bonus + prox_bonus, 1)

        # Days to downgrade estimate
        days = _estimate_days_to_downgrade(progress, rein, under)

        # Build reason list
        reasons: list[str] = []
        if power_state == "Stronghold":
            reasons.append(f"Stronghold — high-value undermine target")
        elif power_state == "Fortified":
            reasons.append(f"Fortified — mid-value undermine target")
        else:
            reasons.append(f"Exploited — low-value undermine target")

        if progress <= 0.0:
            reasons.append("🚨 Already at downgrade threshold — one more push drops it")
        elif progress < 0.2:
            reasons.append(f"Near downgrade threshold ({progress:.1%} progress)")
        elif progress >= 1.0:
            reasons.append(f"Progress at {progress:.1%} — recently reinforced, harder to drop")

        if days is not None and days == 0.0:
            reasons.append("Downgrade happening NOW this cycle")
        elif days is not None and days < 2.0:
            reasons.append(f"~{days:.1f}d to downgrade at current rate")
        elif days is not None and days < 5.0:
            reasons.append(f"~{days:.1f}d to downgrade — moderate pressure")

        if dist_from_attacker is not None:
            if dist_from_attacker <= 5.0:
                reasons.append(f"Extremely close to your territory ({dist_from_attacker:.1f} LY)")
            elif dist_from_attacker <= 15.0:
                reasons.append(f"Close to your territory ({dist_from_attacker:.1f} LY)")

        trend = _trend(sid)
        items.append(TargetAnalysisItem(
            system_id64=system.system_id64,
            system_name=system.name,
            controlling_power=snap["power"],
            power_state=power_state,
            control_progress=progress,
            reinforcement=rein if rein > 0 else None,
            undermining=under if under > 0 else None,
            score=score,
            reasons=reasons,
            distance_from_attacker=dist_from_attacker,
            days_to_downgrade=days,
            trend=trend,
        ))

    items.sort(key=lambda x: x.score, reverse=True)

    return TargetAnalysisResponse(
        targets=items[:50],
        attacker_power=attacker,
        target_powers=targets,
    )


# ---------------------------------------------------------------------------
# GET /api/systems/search  — system name search (for center system selector)
# ---------------------------------------------------------------------------

systems_router = APIRouter(prefix="/systems", tags=["systems"])


@systems_router.get("/search", response_model=list[SystemSearchResult])
def search_systems(
    q: str = Query(default="", min_length=1),
    db: Session = Depends(get_db),
) -> list[SystemSearchResult]:
    """Case-insensitive substring search over known PP system names (max 20)."""
    rows = (
        db.query(PPSystem)
        .filter(PPSystem.name.ilike(f"%{q}%"))
        .order_by(PPSystem.name)
        .limit(20)
        .all()
    )
    return [
        SystemSearchResult(system_id64=s.system_id64, name=s.name, x=s.x, y=s.y, z=s.z)
        for s in rows
    ]


@systems_router.get("/{system_id64}/history", response_model=list[SystemHistoryPoint])
def get_system_history(
    system_id64: int,
    db: Session = Depends(get_db),
) -> list[SystemHistoryPoint]:
    """Return all PP snapshots for a system, ordered chronologically."""
    system = db.query(PPSystem).filter(PPSystem.system_id64 == system_id64).first()
    if system is None:
        return []
    rows = (
        db.query(PPSystemSnapshot)
        .filter(PPSystemSnapshot.system_id == system.id)
        .order_by(PPSystemSnapshot.snapshot_time.asc())
        .all()
    )
    return [
        SystemHistoryPoint(
            snapshot_time=r.snapshot_time,
            power=r.power,
            power_state=r.power_state,
            reinforcement=r.reinforcement,
            undermining=r.undermining,
            control_progress=r.control_progress,
        )
        for r in rows
    ]
