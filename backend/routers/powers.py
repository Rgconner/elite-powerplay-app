"""Powers router — read-only public endpoints for Power Play data."""

import json as _json
import math
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

# Staleness filter for all live data queries.
# Uses Spansh's own updated_at field (authoritative game-data age).
# Systems are considered stale if their data is older than 7 days.
# Rows with NULL spansh_updated_at (ingested before the column was added)
# are kept only if snapshot_time is recent — so old pre-migration rows
# eventually age out rather than persisting forever as "valid".
_STALE_FILTER = """
    AND (
        spansh_updated_at > NOW() - INTERVAL '7 days'
        OR (
            spansh_updated_at IS NULL
            AND snapshot_time > NOW() - INTERVAL '7 days'
        )
    )
"""

from db.session import get_db, IngestSessionLocal
from models.models import PPSystem, PPSystemSnapshot
from models.schemas import (
    ContestedSystemInfo,
    PPSystemEntry,
    PowersList,
    RecommendationsResponse,
    SystemHistoryPoint,
    SystemSearchResult,
    TargetAnalysisItem,
    TargetAnalysisRequest,
    TargetAnalysisResponse,
)
from services.scoring import compute_recommendations, load_weights, DEFAULTS as SCORING_DEFAULTS
from services.decay import effective_undermining as _eff_under

logger = logging.getLogger(__name__)

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
    center_id: Optional[int] = Query(default=None),   # legacy param kept for compatibility
    ref_id:    Optional[int] = Query(default=None),    # preferred param name
    db: Session = Depends(get_db),
) -> list[PPSystemEntry]:
    """
    Return all systems currently under the given Power's influence,
    enriched with their latest PP snapshot.  Optionally compute distance
    from a reference system when ref_id (or legacy center_id) system_id64 is supplied.
    """
    # Accept either ref_id or legacy center_id
    resolved_ref_id = ref_id if ref_id is not None else center_id

    # Latest snapshot per system — exclude stale Spansh data
    latest_sql = text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress,
               snapshot_time, spansh_updated_at,
               cp_decay
        FROM pp_system_snapshots
        WHERE power = :power
        {_STALE_FILTER}
        ORDER BY system_id, snapshot_time DESC
    """)
    snap_rows = db.execute(latest_sql, {"power": name}).mappings().all()

    if not snap_rows:
        return []

    system_ids = [r["system_id"] for r in snap_rows]
    snap_by_id = {r["system_id"]: r for r in snap_rows}

    systems = db.query(PPSystem).filter(PPSystem.id.in_(system_ids)).all()
    sys_by_id = {s.id: s for s in systems}

    # Resolve reference coords
    cx: Optional[float] = None
    cy: Optional[float] = None
    cz: Optional[float] = None
    if resolved_ref_id is not None:
        center_sys = db.query(PPSystem).filter(PPSystem.system_id64 == resolved_ref_id).first()
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
        cp_decay_val = snap["cp_decay"]
        eff_u = _eff_under(under, cp_decay_val)
        undermine_ratio: Optional[float] = None
        if rein and rein > 0:
            undermine_ratio = eff_u / rein

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
            spansh_updated_at=snap["spansh_updated_at"],
            distance_from_center=distance,
            undermine_ratio=undermine_ratio,
            cp_decay=cp_decay_val,
        ))

    return results


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/recommendations
# ---------------------------------------------------------------------------


@router.get("/{name}/recommendations", response_model=RecommendationsResponse)
def get_power_recommendations(
    name: str,
    center_id: Optional[int] = Query(default=None),   # legacy param kept for compatibility
    ref_id:    Optional[int] = Query(default=None),    # preferred param name
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    """Return fortify and expand recommendations for a Power."""
    resolved_ref_id = ref_id if ref_id is not None else center_id
    result = compute_recommendations(name, resolved_ref_id, db)
    return RecommendationsResponse(**result)


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/contested
# ---------------------------------------------------------------------------


@router.get("/{name}/contested", response_model=list[ContestedSystemInfo])
def get_contested_systems(
    name: str,
    db: Session = Depends(get_db),
) -> list[ContestedSystemInfo]:
    """Return all systems currently in Contested state that are relevant to
    the given power (both cases: we are attacking, or we are being attacked).

    Spec:
      1. power_state = 'Contested'
      2. The selected power appears in powers_list AND has progress > 0 in
         conflict_progress (i.e. has actually earned merits there).
      3. Data is not stale (spansh_updated_at within 7 days, or within 7 days
         via snapshot_time when spansh_updated_at IS NULL — controlled by the
         'contested_null_ts_is_stale' admin setting).

    The staleness clause for NULL timestamps is built dynamically based on the
    admin setting so it can be toggled without redeployment.
    """
    # Read the null-timestamp staleness setting
    null_ts_row = db.execute(
        text("SELECT value FROM admin_settings WHERE key = 'contested_null_ts_is_stale' LIMIT 1")
    ).fetchone()
    null_ts_is_stale = (null_ts_row is None) or (null_ts_row[0].lower() not in ("false", "0", "no"))

    if null_ts_is_stale:
        # NULL timestamp → treat as stale: require spansh_updated_at to be present and fresh
        stale_clause = "AND spansh_updated_at > NOW() - INTERVAL '7 days'"
    else:
        # NULL timestamp → keep (legacy pre-migration rows)
        stale_clause = _STALE_FILTER

    # Get the latest snapshot for every Contested system where the selected
    # power appears in powers_list AND has earned merits (progress > 0 in
    # conflict_progress JSON).  This covers both directions:
    #   - Our power is attacking an enemy-controlled Contested system
    #   - An enemy is attacking one of our Contested systems
    # The conflict_progress filter is applied in Python after the DB fetch
    # because conflict_progress is a JSON string, not a SQL-queryable column.
    contested_rows = db.execute(text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               control_progress, reinforcement, undermining,
               powers_list, conflict_progress, spansh_updated_at
        FROM pp_system_snapshots
        WHERE power_state = 'Contested'
          AND powers_list ILIKE :power_pattern
          {stale_clause}
        ORDER BY system_id, snapshot_time DESC
    """), {"power_pattern": f"%{name}%"}).mappings().all()

    if not contested_rows:
        return []

    contested_sys_ids = [r["system_id"] for r in contested_rows]
    contested_snaps   = {r["system_id"]: r for r in contested_rows}

    # Fetch system coords
    contested_systems = db.query(PPSystem).filter(
        PPSystem.id.in_(contested_sys_ids)
    ).all()
    sys_by_id = {s.id: s for s in contested_systems}

    # Get coords for the selected power's systems to compute distance (no stale filter
    # here — we want all territory coords even if data is slightly old)
    power_snap_rows = db.execute(text("""
        SELECT DISTINCT ON (system_id) system_id
        FROM pp_system_snapshots
        WHERE power = :power
        ORDER BY system_id, snapshot_time DESC
    """), {"power": name}).mappings().all()

    power_sys_ids = [r["system_id"] for r in power_snap_rows]
    power_systems = db.query(PPSystem).filter(
        PPSystem.id.in_(power_sys_ids)
    ).all() if power_sys_ids else []
    power_coords = [
        (s.x or 0.0, s.y or 0.0, s.z or 0.0) for s in power_systems
    ]

    results: list[ContestedSystemInfo] = []
    for sid, snap in contested_snaps.items():
        system = sys_by_id.get(sid)
        if system is None:
            continue

        # ── Condition 2b: selected power must have progress > 0 ──────────────
        # Parse conflict_progress JSON and verify the power has merits there.
        cp_str = snap["conflict_progress"] or ""
        power_has_merits = False
        if cp_str:
            try:
                cp_entries = _json.loads(cp_str)
                for entry in cp_entries:
                    if isinstance(entry, dict) and entry.get("power") == name:
                        if (entry.get("progress") or 0) > 0:
                            power_has_merits = True
                        break
            except Exception:
                pass
        if not power_has_merits:
            continue

        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0

        dist: Optional[float] = None
        if power_coords:
            dist = min(
                _dist3(sx, sy, sz, cx, cy, cz)
                for cx, cy, cz in power_coords
            )

        # Build a friendly controlling_power label from powers_list
        pl = snap["powers_list"] or ""
        powers = [p.strip() for p in pl.split(",") if p.strip()]
        label = "Multiple" if len(powers) > 1 else (powers[0] if powers else "Unknown")

        results.append(ContestedSystemInfo(
            system_id64=system.system_id64,
            system_name=system.name,
            controlling_power=label,
            power_state="Contested",
            control_progress=snap["control_progress"],
            reinforcement=snap["reinforcement"] if (snap["reinforcement"] or 0) > 0 else None,
            undermining=snap["undermining"] if (snap["undermining"] or 0) > 0 else None,
            distance_from_power=dist,
            x=sx, y=sy, z=sz,
            powers_list=snap["powers_list"],
            conflict_progress=snap["conflict_progress"],
            spansh_updated_at=snap["spansh_updated_at"],
        ))

    # Sort by distance to the selected power's territory
    results.sort(key=lambda r: r.distance_from_power if r.distance_from_power is not None else 9999.0)
    return results


# ---------------------------------------------------------------------------
# POST /api/powers/target-analysis
# ---------------------------------------------------------------------------


def _dist3(ax: float, ay: float, az: float,
           bx: float, by: float, bz: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _estimate_days_to_downgrade(
    progress: float,
    reinforcement: int,
    undermining: int,
    power_state: Optional[str] = None,
) -> Optional[float]:
    """Estimate days until progress hits 0.0 (state downgrade) at current rate.

    Uses the same cumulative-cycle-divided-by-days approach as the fortify scorer.
    """
    from services.scoring import days_elapsed_in_cycle
    if progress <= 0.0:
        return 0.0
    net_loss_cycle = undermining - reinforcement   # positive = losing ground
    if net_loss_cycle <= 0:
        return None                                 # enemy winning — no downgrade
    elapsed = days_elapsed_in_cycle()
    daily_net_loss = net_loss_cycle / elapsed
    from services.scoring import _band_width
    band = _band_width(power_state)
    buffer = progress * band
    daily_scaled = daily_net_loss   # R/U are in raw merits; buffer is in merits too
    if daily_scaled <= 0:
        return None
    return buffer / daily_scaled


@router.post("/target-analysis", response_model=TargetAnalysisResponse)
def target_analysis(
    body: TargetAnalysisRequest,
    db: Session = Depends(get_db),
) -> TargetAnalysisResponse:
    """
    Score enemy systems for undermining priority.

    Scoring model (all weights configurable via Admin panel → admin_settings):
      Base score by state:
        Stronghold = target_score_stronghold  (default 1000)
        Fortified  = target_score_fortified   (default 600)
        Exploited  = target_score_exploited   (default 200)
        Contested  = target_score_contested   (default 800)
      Progress bonus: target_progress_bonus_max × (1 − progress)
        — closer enemy progress to 0 = higher bonus
      Proximity bonus: target_prox_bonus_max × max(0, 1 − dist/target_dist_max_ly)
        — closer to attacker = higher bonus
      Max results: target_max_results (default 50)

    Includes Contested systems (power_state = "Contested") where our power
    already has a foothold but hasn't flipped the system yet.
    """
    # ── 0. Load configurable weights from DB ─────────────────────────────────
    w = load_weights(db)

    score_stronghold  = float(w.get("target_score_stronghold",  SCORING_DEFAULTS["target_score_stronghold"]))
    score_fortified   = float(w.get("target_score_fortified",   SCORING_DEFAULTS["target_score_fortified"]))
    score_exploited   = float(w.get("target_score_exploited",   SCORING_DEFAULTS["target_score_exploited"]))
    score_contested   = float(w.get("target_score_contested",   SCORING_DEFAULTS["target_score_contested"]))
    prog_bonus_max    = float(w.get("target_progress_bonus_max",SCORING_DEFAULTS["target_progress_bonus_max"]))
    prox_bonus_max    = float(w.get("target_prox_bonus_max",    SCORING_DEFAULTS["target_prox_bonus_max"]))
    dist_max_ly       = float(w.get("target_dist_max_ly",       SCORING_DEFAULTS["target_dist_max_ly"]))
    max_results       = int(float(w.get("target_max_results",   SCORING_DEFAULTS["target_max_results"])))

    # Thresholds returned to the UI for calibrated colour labels
    prog_critical = float(w.get("target_progress_critical", SCORING_DEFAULTS["target_progress_critical"]))
    prog_high     = float(w.get("target_progress_high",     SCORING_DEFAULTS["target_progress_high"]))
    prog_medium   = float(w.get("target_progress_medium",   SCORING_DEFAULTS["target_progress_medium"]))

    attacker = body.attacker_power
    targets  = body.target_powers

    # ── 1. Get attacker's system coords ──────────────────────────────────────
    attacker_snap_rows = db.execute(text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power
        FROM pp_system_snapshots
        WHERE power = :power
        {_STALE_FILTER}
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
            targets=[], attacker_power=attacker, target_powers=targets,
            progress_thresholds={"critical": prog_critical, "high": prog_high, "medium": prog_medium},
        )

    target_snap_rows = db.execute(text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress,
               cp_decay
        FROM pp_system_snapshots
        WHERE power = ANY(:powers)
        {_STALE_FILTER}
        ORDER BY system_id, snapshot_time DESC
    """), {"powers": targets}).mappings().all()

    # ── 2b. Contested systems — spec-correct query ────────────────────────────
    # A system is a Contested Target when ALL THREE conditions hold:
    #   1. power_state = 'Contested'  (not Acquisition or any other state)
    #   2. The attacker power is in powers_list AND has progress > 0
    #      in conflict_progress  (has actually earned merits there)
    #   3. Data is fresh (spansh_updated_at within 7 days, or within 7 days via
    #      snapshot_time when spansh_updated_at IS NULL per admin setting)
    #
    # Contested rows have power = NULL (set by ingestion), so they are NOT
    # returned by the target_snap_rows query above.  We fetch them separately
    # and merge them into snap_by_id so they participate in scoring.
    #
    # Both directions are surfaced:
    #   - Our power attacking an enemy-held Contested system (common)
    #   - Enemy attacking one of our Contested systems (defensive alert)

    null_ts_row = db.execute(
        text("SELECT value FROM admin_settings WHERE key = 'contested_null_ts_is_stale' LIMIT 1")
    ).fetchone()
    null_ts_is_stale = (null_ts_row is None) or (null_ts_row[0].lower() not in ("false", "0", "no"))
    contested_stale_clause = (
        "AND spansh_updated_at > NOW() - INTERVAL '7 days'"
        if null_ts_is_stale else _STALE_FILTER
    )

    contested_snap_rows = db.execute(text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress,
               powers_list, conflict_progress,
               cp_decay
        FROM pp_system_snapshots
        WHERE power_state = 'Contested'
          AND powers_list ILIKE :attacker_pattern
          {contested_stale_clause}
        ORDER BY system_id, snapshot_time DESC
    """), {"attacker_pattern": f"%{attacker}%"}).mappings().all()

    # Filter in Python: attacker must have progress > 0 in conflict_progress
    contested_sys_ids: set[int] = set()
    contested_extra_snaps: dict[int, object] = {}
    for row in contested_snap_rows:
        cp_str = row["conflict_progress"] or ""
        has_merits = False
        if cp_str:
            try:
                for entry in _json.loads(cp_str):
                    if isinstance(entry, dict) and entry.get("power") == attacker:
                        if (entry.get("progress") or 0) > 0:
                            has_merits = True
                        break
            except Exception:
                pass
        if has_merits:
            contested_sys_ids.add(row["system_id"])
            contested_extra_snaps[row["system_id"]] = row

    target_sys_ids = [r["system_id"] for r in target_snap_rows]
    # Merge Contested system IDs — these have power=NULL so they won't clash
    # with target_snap_rows (which only fetches power = ANY(:powers) rows)
    all_fetch_ids = list(set(target_sys_ids) | set(contested_extra_snaps.keys()))
    target_systems_orm = db.query(PPSystem).filter(
        PPSystem.id.in_(all_fetch_ids)
    ).all()
    sys_by_id = {s.id: s for s in target_systems_orm}
    snap_by_id: dict = {r["system_id"]: r for r in target_snap_rows}
    # Add Contested rows; if a system appears in both lists the target-power row
    # takes precedence (it has richer data), otherwise add the Contested row.
    for sid, crow in contested_extra_snaps.items():
        if sid not in snap_by_id:
            snap_by_id[sid] = crow

    # ── 3. Get progress trends for all target systems ─────────────────────────
    # Include both regular target and contested system IDs so contested
    # systems also get trend data instead of always showing "unknown".
    all_trend_ids = list(set(target_sys_ids) | set(contested_extra_snaps.keys()))
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
    """), {"ids": all_trend_ids}).mappings().all()

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
        is_contested = sid in contested_sys_ids

        if power_state not in ("Stronghold", "Fortified", "Exploited", "Contested"):
            continue   # skip Unoccupied — nothing to undermine

        progress   = snap["control_progress"] or 0.5
        rein       = snap["reinforcement"] or 0
        under      = snap["undermining"]   or 0
        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0

        # Base score by state tier (or Contested override)
        if is_contested:
            base = score_contested
        elif power_state == "Stronghold":
            base = score_stronghold
        elif power_state == "Fortified":
            base = score_fortified
        else:
            base = score_exploited

        # Progress bonus: the closer to 0 the more vulnerable
        # progress ≤0 → full bonus; progress ≥1 → no bonus
        prog_clamped = max(0.0, min(1.0, progress))
        progress_bonus = prog_bonus_max * (1.0 - prog_clamped)

        # Proximity bonus
        dist_from_attacker: Optional[float] = None
        prox_bonus = 0.0
        if attacker_coords:
            dist_from_attacker = min(
                _dist3(sx, sy, sz, ax, ay, az)
                for ax, ay, az in attacker_coords
            )
            if dist_from_attacker <= dist_max_ly:
                prox_bonus = prox_bonus_max * max(
                    0.0, 1.0 - dist_from_attacker / dist_max_ly
                )

        score = round(base + progress_bonus + prox_bonus, 1)

        # Days to downgrade estimate — use actual state for correct band width
        days = _estimate_days_to_downgrade(progress, rein, under, power_state)

        # Build reason list
        reasons: list[str] = []
        if is_contested:
            reasons.append("⚔ Contested — your power already has a foothold here")
        elif power_state == "Stronghold":
            reasons.append("Stronghold — high-value undermine target")
        elif power_state == "Fortified":
            reasons.append("Fortified — mid-value undermine target")
        else:
            reasons.append("Exploited — low-value undermine target")

        if progress <= 0.0:
            reasons.append("🚨 Already at downgrade threshold — one more push drops it")
        elif progress < prog_critical:
            reasons.append(f"CRITICAL vulnerability ({progress:.1%} progress — near collapse)")
        elif progress < prog_high:
            reasons.append(f"HIGH vulnerability ({progress:.1%} progress)")
        elif progress < prog_medium:
            reasons.append(f"Moderate vulnerability ({progress:.1%} progress)")
        elif progress >= 1.0:
            reasons.append(f"Progress at {progress:.1%} — recently reinforced, harder to drop")

        if days is not None and days == 0.0:
            reasons.append("Downgrade happening NOW this cycle")
        elif days is not None and days < 2.0:
            reasons.append(f"~{days:.1f}d to downgrade at current rate")
        elif days is not None and days < 7.0:
            reasons.append(f"~{days:.1f}d to downgrade — apply pressure now")

        if dist_from_attacker is not None:
            if dist_from_attacker <= 5.0:
                reasons.append(f"Extremely close to your territory ({dist_from_attacker:.1f} LY)")
            elif dist_from_attacker <= 15.0:
                reasons.append(f"Close to your territory ({dist_from_attacker:.1f} LY)")

        trend = _trend(sid)

        # Derive controlling_power: for contested systems power is NULL,
        # so build a label from powers_list (same as get_contested_systems endpoint).
        ctrl_power = snap["power"]
        if ctrl_power is None:
            pl = (snap["powers_list"] or "") if "powers_list" in snap.keys() else ""
            powers = [p.strip() for p in pl.split(",") if p.strip()]
            ctrl_power = "Multiple" if len(powers) > 1 else (powers[0] if powers else "Unknown")

        items.append(TargetAnalysisItem(
            system_id64=system.system_id64,
            system_name=system.name,
            controlling_power=ctrl_power,
            power_state=power_state,
            control_progress=progress,
            reinforcement=rein if rein > 0 else None,
            undermining=under if under > 0 else None,
            score=score,
            reasons=reasons,
            distance_from_attacker=dist_from_attacker,
            days_to_downgrade=days,
            trend=trend,
            contested=is_contested,
            cp_decay=snap.get("cp_decay"),
        ))

    # Sort by control_progress ascending (lowest = most vulnerable) before
    # truncating to max_results.  This ensures the cap keeps the most
    # actionable targets rather than simply the highest-scored ones.
    # The frontend re-sorts by any column the user clicks afterwards.
    items.sort(key=lambda x: (x.control_progress if x.control_progress is not None else 1.0))

    return TargetAnalysisResponse(
        targets=items[:max_results],
        attacker_power=attacker,
        target_powers=targets,
        progress_thresholds={
            "critical": prog_critical,
            "high":     prog_high,
            "medium":   prog_medium,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/powers/refresh-stale  — async refresh stale system data
# ---------------------------------------------------------------------------


class RefreshStaleRequest(BaseModel):
    system_ids: list[int]


class RefreshStaleResponse(BaseModel):
    status: str
    count: int
    message: str


def _refresh_stale_sync(system_ids: list[int]):
    """Synchronous background task to refresh stale systems.
    
    Called via BackgroundTasks — runs in a separate thread with its own DB session.
    Iterates over the requested systems, fetches fresh data from Spansh,
    and inserts new snapshot rows.
    """
    db = IngestSessionLocal()
    try:
        from services.decay import compute_cp_decay, current_cycle_start
        cycle = current_cycle_start()
        count = 0

        for sid in system_ids:
            # Fetch from Spansh
            system_obj = None
            try:
                import httpx
                payload = {
                    "filters": {"id64": {"value": [sid], "comparison": "="}},
                    "size": 1,
                    "page": 0,
                }
                resp = httpx.post(
                    "https://spansh.co.uk/api/systems/search",
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        system_obj = results[0]
            except Exception as e:
                logger.warning("Refresh stale: Spansh fetch failed for system %d: %s", sid, e)
                continue

            if system_obj is None:
                logger.warning("Refresh stale: no data returned for system %d", sid)
                continue

            # Parse fields (mirrors ingestion.py logic)
            name: str = system_obj.get("name", "")
            x = system_obj.get("x")
            y = system_obj.get("y")
            z = system_obj.get("z")
            allegiance = system_obj.get("allegiance")
            population = system_obj.get("population")
            power_state = system_obj.get("power_state")
            control_progress = system_obj.get("power_state_control_progress")
            reinforcement = system_obj.get("power_state_reinforcement")
            undermining = system_obj.get("power_state_undermining")

            # Parse powers_list and conflict_progress
            raw_power = system_obj.get("power")
            if isinstance(raw_power, list) and raw_power:
                powers_list = ",".join(str(p) for p in raw_power)
            elif isinstance(raw_power, str) and raw_power:
                powers_list = raw_power
            else:
                powers_list = None

            raw_cp = system_obj.get("power_conflict_progress")
            conflict_progress = _json.dumps(raw_cp) if raw_cp else None

            # Parse spansh_updated_at
            spansh_updated_at = None
            raw_updated = system_obj.get("updated_at")
            if raw_updated:
                try:
                    spansh_updated_at = datetime.fromisoformat(
                        str(raw_updated).replace("+00", "+00:00")
                    ).replace(tzinfo=None)
                except Exception:
                    pass

            # Upsert pp_systems
            sys_result = db.execute(
                text("""
                    INSERT INTO pp_systems (system_id64, name, x, y, z, allegiance, population)
                    VALUES (:id64, :name, :x, :y, :z, :allegiance, :population)
                    ON CONFLICT (system_id64) DO UPDATE
                        SET name = EXCLUDED.name, x = EXCLUDED.x, y = EXCLUDED.y,
                            z = EXCLUDED.z, allegiance = EXCLUDED.allegiance,
                            population = EXCLUDED.population
                    RETURNING id
                """),
                {"id64": sid, "name": name, "x": x, "y": y, "z": z,
                 "allegiance": allegiance, "population": population},
            )
            system_db_id = sys_result.scalar_one()

            # Find power name for this system (use existing snapshot's power)
            power_row = db.execute(
                text("""
                    SELECT power FROM pp_system_snapshots
                    WHERE system_id = :sid AND power IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1
                """),
                {"sid": system_db_id},
            ).fetchone()
            power_name = power_row[0] if power_row else None

            if power_name is None:
                logger.warning("Refresh stale: no power found for system %d, skipping", sid)
                continue

            # Compute CP decay
            cp_decay_val = compute_cp_decay(power_state, control_progress, undermining)

            # Insert snapshot
            db.execute(
                text("""
                    INSERT INTO pp_system_snapshots
                        (system_id, ingestion_run_id, snapshot_time,
                         spansh_updated_at, power, power_state, control_progress,
                         reinforcement, undermining, powers_list, conflict_progress,
                         cp_decay, decay_cycle_start)
                    VALUES
                        (:system_id, NULL, :now, :spansh_updated_at, :power, :power_state,
                         :control_progress, :reinforcement, :undermining,
                         :powers_list, :conflict_progress, :cp_decay, :decay_cycle_start)
                """),
                {
                    "system_id": system_db_id,
                    "now": datetime.utcnow(),
                    "spansh_updated_at": spansh_updated_at,
                    "power": power_name,
                    "power_state": power_state,
                    "control_progress": control_progress,
                    "reinforcement": reinforcement,
                    "undermining": undermining,
                    "powers_list": powers_list,
                    "conflict_progress": conflict_progress,
                    "cp_decay": cp_decay_val,
                    "decay_cycle_start": cycle,
                },
            )
            count += 1

            # Commit every system
            db.commit()
            time.sleep(0.25)  # rate limit: be polite to Spansh

        logger.info("Refresh stale: refreshed %d / %d systems", count, len(system_ids))

    except Exception:
        logger.exception("Refresh stale background task failed")
        db.rollback()
    finally:
        db.close()


@router.post("/refresh-stale", response_model=RefreshStaleResponse)
async def refresh_stale(
    body: RefreshStaleRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RefreshStaleResponse:
    """Trigger an async refresh of stale Power Play data for the given systems.
    
    Accepts a list of system_id64 values. Returns immediately with 202 Accepted,
    while a background task fetches fresh data from Spansh and inserts new
    snapshot rows. The frontend should re-fetch the power systems after a delay
    to pick up the refreshed data.
    """
    ids = body.system_ids
    if not ids:
        return RefreshStaleResponse(
            status="error", count=0,
            message="No system IDs provided",
        )

    # Deduplicate
    seen: set[int] = set()
    unique_ids = [s for s in ids if not (s in seen or seen.add(s))]

    background_tasks.add_task(_refresh_stale_sync, unique_ids)

    return RefreshStaleResponse(
        status="refreshing",
        count=len(unique_ids),
        message=f"Queued {len(unique_ids)} system(s) for async refresh from Spansh",
    )


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/expand-debug  — diagnostic: show expand candidates
# ---------------------------------------------------------------------------


@router.get("/{name}/expand-debug")
def expand_debug(
    name: str,
    merits_max: int = Query(default=120000, description="Only show systems with ≤ this many merits remaining"),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Diagnostic endpoint: return raw expand candidates for a power with full details.

    Returns systems that:
      1. Have fresh Spansh data (spansh_updated_at < 7 days, or snapshot_time < 7 days for NULL)
      2. Are Unoccupied (power_state = 'Unoccupied')
      3. Are within 20 LY of a Fortified system OR 30 LY of a Stronghold system
      4. Have merits_remaining <= merits_max (120,000 if unfiltered)

    Sorted by merits_remaining ascending (closest to acquisition first).
    """
    from services.scoring import (
        get_latest_snapshots, load_weights,
        MERIT_ACQUIRE, DEFAULTS as SC_DEFAULTS, _dist,
    )
    from models.models import PPSystem

    weights   = load_weights(db)
    snapshots = get_latest_snapshots(db)

    fort_max = float(weights.get("expand_fortified_dist_ly",  SC_DEFAULTS["expand_fortified_dist_ly"]))
    sh_max   = float(weights.get("expand_stronghold_dist_ly", SC_DEFAULTS["expand_stronghold_dist_ly"]))

    # Identify this power's systems and their states
    power_sys_ids = {sid for sid, s in snapshots.items() if s.get("power") == name}
    if not power_sys_ids:
        return {"error": f"No fresh snapshots found for power '{name}'", "systems": []}

    power_systems = db.query(PPSystem).filter(PPSystem.id.in_(power_sys_ids)).all()

    fortified_coords:  list[tuple[float, float, float]] = []
    stronghold_coords: list[tuple[float, float, float]] = []
    for s in power_systems:
        state = snapshots[s.id].get("power_state")
        coord = (s.x or 0.0, s.y or 0.0, s.z or 0.0)
        if state == "Fortified":
            fortified_coords.append(coord)
        elif state == "Stronghold":
            stronghold_coords.append(coord)

    power_coords = [(s.x or 0.0, s.y or 0.0, s.z or 0.0) for s in power_systems]
    all_x = [c[0] for c in power_coords]
    all_y = [c[1] for c in power_coords]
    all_z = [c[2] for c in power_coords]
    bbox_pad = max(fort_max, sh_max)

    candidates = db.query(PPSystem).filter(
        PPSystem.x.between(min(all_x) - bbox_pad, max(all_x) + bbox_pad),
        PPSystem.y.between(min(all_y) - bbox_pad, max(all_y) + bbox_pad),
        PPSystem.z.between(min(all_z) - bbox_pad, max(all_z) + bbox_pad),
        PPSystem.id.notin_(power_sys_ids),
    ).all()

    results = []
    for system in candidates:
        snap = snapshots.get(system.id)
        if snap is None:
            continue  # no fresh data
        if snap.get("power_state") != "Unoccupied":
            continue  # must be Unoccupied

        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0
        dist_fort = min((_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in fortified_coords), default=9999.0)
        dist_sh   = min((_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in stronghold_coords), default=9999.0)
        in_fort   = dist_fort <= fort_max
        in_sh     = dist_sh   <= sh_max

        if not (in_fort or in_sh):
            continue

        progress     = float(snap.get("control_progress") or 0.0)
        merit_pos    = round(progress * MERIT_ACQUIRE)
        merits_left  = max(0, MERIT_ACQUIRE - merit_pos)

        if merits_left > merits_max:
            continue

        spansh_ts   = snap.get("spansh_updated_at")
        snapshot_ts = snap.get("snapshot_time")

        results.append({
            "system_name":      system.name,
            "system_id64":      system.system_id64,
            "power_state":      snap.get("power_state"),
            "control_progress": round(progress, 4),
            "merit_position":   merit_pos,
            "merits_remaining": merits_left,
            "in_fort_range":    in_fort,
            "dist_fort_ly":     round(dist_fort, 2) if in_fort else None,
            "in_sh_range":      in_sh,
            "dist_sh_ly":       round(dist_sh, 2) if in_sh else None,
            "anchor_type":      "both" if (in_fort and in_sh) else ("fortified" if in_fort else "stronghold"),
            "allegiance":       system.allegiance,
            "spansh_updated_at": str(spansh_ts) if spansh_ts else None,
            "snapshot_time":     str(snapshot_ts) if snapshot_ts else None,
        })

    results.sort(key=lambda r: r["merits_remaining"])
    return {
        "power": name,
        "fort_max_ly": fort_max,
        "sh_max_ly": sh_max,
        "merits_max_filter": merits_max,
        "fortified_anchor_count": len(fortified_coords),
        "stronghold_anchor_count": len(stronghold_coords),
        "total_candidates_returned": len(results),
        "systems": results[:limit],
    }


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
            cp_decay=r.cp_decay,
        )
        for r in rows
    ]