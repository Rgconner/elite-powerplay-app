"""Powers router — read-only public endpoints for Power Play data."""

import json as _json
import math
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
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
from services.scoring import compute_recommendations, load_weights, DEFAULTS as SCORING_DEFAULTS, classify_acquisition, contested_min_progress, fraction_setting, parse_conflict_progress
from services.decay import effective_undermining as _eff_under

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/powers", tags=["powers"])


# ---------------------------------------------------------------------------
# GET /api/powers  — list all known powers from latest snapshots
# ---------------------------------------------------------------------------


@router.get("", response_model=PowersList)
def list_powers(db: Session = Depends(get_db)) -> PowersList:
    """Return all distinct power names present in the latest snapshot data."""
    try:
        rows = db.execute(
            text("""
                SELECT DISTINCT power
                FROM pp_system_snapshots
                WHERE power IS NOT NULL
                ORDER BY power
            """)
        ).all()
        return PowersList(powers=[r.power for r in rows])
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_powers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/powers/search  — autocomplete for power names
# ---------------------------------------------------------------------------


@router.get("/search", response_model=PowersList)
def search_powers(
    q: str = Query(default="", min_length=1),
    db: Session = Depends(get_db),
) -> PowersList:
    """Case-insensitive substring search over power names."""
    try:
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("search_powers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    try:
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_power_systems failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    try:
        resolved_ref_id = ref_id if ref_id is not None else center_id
        result = compute_recommendations(name, resolved_ref_id, db)
        return RecommendationsResponse(**result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_power_recommendations failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
      1. power_state = 'Contested' (our storage label for Unoccupied systems)
      2. The selected power AND at least one rival are each at or above the
         contested_min_progress admin setting (default 50%) in
         conflict_progress -- scoring.classify_acquisition.
      3. Data is not stale (spansh_updated_at within 7 days, or within 7 days
         via snapshot_time when spansh_updated_at IS NULL — controlled by the
         'contested_null_ts_is_stale' admin setting).

    The staleness clause for NULL timestamps is built dynamically based on the
    admin setting so it can be toggled without redeployment.
    """
    try:

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

        threshold = contested_min_progress(load_weights(db))

        results: list[ContestedSystemInfo] = []
        for sid, snap in contested_snaps.items():
            system = sys_by_id.get(sid)
            if system is None:
                continue

            # ── Condition 2b: we and >= 1 rival each at contested_min_progress ──
            # Same rule the expansion list uses to exclude these, so a system
            # is in exactly one of the two lists (see scoring.classify_acquisition).
            if classify_acquisition(name, snap["conflict_progress"], threshold) != "contested":
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_contested_systems failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    try:
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
        # (the Admin page saves these as percents; fraction_setting normalises)
        prog_critical = fraction_setting(w, "target_progress_critical")
        prog_high     = fraction_setting(w, "target_progress_high")
        prog_medium   = fraction_setting(w, "target_progress_medium")

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
        #   2. The attacker AND >= 1 rival are each at contested_min_progress
        #      in conflict_progress
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

        # Same contested rule as the Contested list (scoring.classify_acquisition)
        threshold = contested_min_progress(load_weights(db))
        contested_sys_ids: set[int] = set()
        contested_extra_snaps: dict[int, object] = {}
        for row in contested_snap_rows:
            if classify_acquisition(attacker, row["conflict_progress"], threshold) == "contested":
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("target_analysis failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
            cp_decay_val = compute_cp_decay(power_state, control_progress, reinforcement, undermining)

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
    try:
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("refresh_stale failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/expand-debug  — diagnostic: show expand candidates
# ---------------------------------------------------------------------------


@router.get("/{name}/expand-debug")
def expand_debug(
    name: str,
    bucket: Optional[str] = Query(default=None, description="'contested', 'expansion' or 'none' to filter"),
    limit: int = Query(default=50, le=500),
    db: Session = Depends(get_db),
):
    """Diagnostic: how every fresh Unoccupied system the power is present in
    is classified (scoring.classify_acquisition), highest progress first."""
    try:
        threshold = contested_min_progress(load_weights(db))
        rows = db.execute(text(f"""
            SELECT DISTINCT ON (s.system_id)
                   s.system_id, p.system_id64, p.name, s.conflict_progress,
                   s.powers_list, s.spansh_updated_at
            FROM pp_system_snapshots s JOIN pp_systems p ON p.id = s.system_id
            WHERE s.power_state = 'Contested'
              AND s.powers_list ILIKE :pattern
              {_STALE_FILTER.replace("spansh_updated_at", "s.spansh_updated_at").replace("snapshot_time", "s.snapshot_time")}
            ORDER BY s.system_id, s.snapshot_time DESC
        """), {"pattern": f"%{name}%"}).mappings().all()

        counts: dict[str, int] = {"contested": 0, "expansion": 0, "none": 0}
        systems = []
        for r in rows:
            if name not in (r["powers_list"] or "").split(","):
                continue
            kind = classify_acquisition(name, r["conflict_progress"], threshold) or "none"
            counts[kind] += 1
            if bucket and kind != bucket:
                continue
            progress = parse_conflict_progress(r["conflict_progress"])
            rivals = sorted(((p, v) for p, v in progress.items() if p != name), key=lambda x: -x[1])
            systems.append({
                "system_name":      r["name"],
                "system_id64":      r["system_id64"],
                "bucket":           kind,
                "our_progress":     round(progress.get(name, 0.0), 4),
                "top_rival":        rivals[0][0] if rivals else None,
                "top_rival_progress": round(rivals[0][1], 4) if rivals else None,
                "spansh_updated_at": str(r["spansh_updated_at"]) if r["spansh_updated_at"] else None,
            })

        systems.sort(key=lambda s: -s["our_progress"])
        return {
            "power": name,
            "contested_min_progress": threshold,
            "counts": counts,
            "systems": systems[:limit],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("expand_debug failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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


# ---------------------------------------------------------------------------
# GET /api/powers/{name}/realtime  — blended Spansh + EDDN realtime data
# ---------------------------------------------------------------------------


@router.get("/{name}/realtime")
def get_power_realtime(
    name: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return effective (blended) values: Spansh base + EDDN realtime deltas.

    For each system under this power's influence, returns:
    - Standard Spansh snapshot fields (reinforcement, undermining, control_progress)
    - Realtime delta fields (merits_since_spansh, cp_since_spansh)
    - Effective totals (effective_reinforcement, effective_undermining)
    - Live flag indicating whether realtime data is present

    The realtime data comes from pp_realtime_state table, which is updated
    every 60 seconds by the realtime_accumulator service.
    """
    try:
        # Get latest Spansh snapshots for this power
        latest_sql = text(f"""
            SELECT DISTINCT ON (system_id)
                   system_id, power, power_state,
                   reinforcement, undermining, control_progress,
                   snapshot_time, spansh_updated_at
            FROM pp_system_snapshots
            WHERE power = :power
            {_STALE_FILTER}
            ORDER BY system_id, snapshot_time DESC
        """)
        snap_rows = db.execute(latest_sql, {"power": name}).mappings().all()
    
        if not snap_rows:
            return {"systems": [], "total_live_systems": 0}
    
        system_ids = [r["system_id"] for r in snap_rows]
        snap_by_id = {r["system_id"]: r for r in snap_rows}
    
        # Get system details
        systems = db.query(PPSystem).filter(PPSystem.id.in_(system_ids)).all()
        sys_by_id = {s.id: s for s in systems}
    
        # Get realtime state for all these systems
        realtime_rows = db.execute(
            text("""
                SELECT system_id64, merits_since_ts, cp_since_ts,
                       cp_as_reinforcement, cp_as_undermining,
                       latest_event_ts, refreshed_at
                FROM pp_realtime_state
                WHERE power = :power
                  AND system_id64 = ANY(:system_id64s)
            """),
            {
                "power": name,
                "system_id64s": [s.system_id64 for s in systems],
            },
        ).mappings().all()
    
        realtime_by_id64 = {r["system_id64"]: r for r in realtime_rows}
    
        # Build response
        results = []
        total_live = 0
    
        for sid, snap in snap_by_id.items():
            system = sys_by_id.get(sid)
            if system is None:
                continue
        
            # Base Spansh values
            base_reinforcement = snap["reinforcement"] or 0
            base_undermining = snap["undermining"] or 0
            base_control_progress = snap["control_progress"] or 0.0
        
            # Realtime delta (if available)
            realtime = realtime_by_id64.get(system.system_id64)
        
            if realtime and realtime["merits_since_ts"] > 0:
                # Has live data
                cp_reinforcement = float(realtime["cp_as_reinforcement"] or 0)
                cp_undermining = float(realtime["cp_as_undermining"] or 0)
            
                effective_reinforcement = base_reinforcement + cp_reinforcement
                effective_undermining = base_undermining + cp_undermining
            
                # Recompute control_progress with effective values
                # This is a simplified calculation — full logic would use scoring.py
                net_cp = effective_reinforcement - effective_undermining
                effective_control_progress = max(0.0, base_control_progress + (net_cp / 1000.0))
            
                is_live = True
                total_live += 1
            else:
                # No live data
                effective_reinforcement = base_reinforcement
                effective_undermining = base_undermining
                effective_control_progress = base_control_progress
                is_live = False
                cp_reinforcement = 0.0
                cp_undermining = 0.0
        
            results.append({
                "system_id64": system.system_id64,
                "name": system.name,
                "power_state": snap["power_state"],
                "base_reinforcement": base_reinforcement,
                "base_undermining": base_undermining,
                "base_control_progress": base_control_progress,
                "realtime": {
                    "merits_since_spansh": realtime["merits_since_ts"] if realtime else 0,
                    "cp_since_spansh": float(realtime["cp_since_ts"]) if realtime else 0.0,
                    "cp_as_reinforcement": cp_reinforcement,
                    "cp_as_undermining": cp_undermining,
                    "latest_event_at": realtime["latest_event_ts"].isoformat() if realtime and realtime["latest_event_ts"] else None,
                    "refreshed_at": realtime["refreshed_at"].isoformat() if realtime and realtime["refreshed_at"] else None,
                } if realtime else None,
                "effective_reinforcement": effective_reinforcement,
                "effective_undermining": effective_undermining,
                "effective_control_progress": effective_control_progress,
                "is_live": is_live,
            })
    
        return {
            "systems": results,
            "total_live_systems": total_live,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_power_realtime failed")
        raise HTTPException(status_code=500, detail="Internal server error")
