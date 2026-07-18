"""Power Play 2.0 recommendation scoring engine.

═══════════════════════════════════════════════════════════════
PP 2.0 MECHANICS (confirmed from live Spansh API data, July 2026)
═══════════════════════════════════════════════════════════════

Actual states in the wild:   Exploited | Fortified | Stronghold | Unoccupied
Fields per system:
  power_state_reinforcement   (int)   — total reinforcement delivered this cycle
  power_state_undermining     (int)   — total undermining delivered this cycle
  power_state_control_progress (float) — normalized net score:
      < 0.0  → system is ALREADY past the downgrade threshold (losing NOW)
      0.0–1.0 → between thresholds (normal operational range)
      ≥ 1.0  → upgrade threshold crossed (next level imminent / already counted)

The PP cycle resets weekly.  Within a cycle:
  - Each tick the game re-computes control_progress from R and U deliveries.
  - progress ≈ (net deliveries) / (threshold to next level)
  - A negative progress means U has overcome R past the downgrade boundary.

STATE TRANSITIONS (direction and what stops them):
  Exploited  → degrades to Unoccupied if progress reaches 0.0
  Fortified  → degrades to Exploited  if progress reaches 0.0
  Stronghold → degrades to Fortified  if progress reaches 0.0
  Exploited  → upgrades to Fortified  if progress reaches 1.0
  Fortified  → upgrades to Stronghold if progress reaches 1.0
  (Stronghold has no upgrade)

URGENCY MODEL used by this engine:
  Current Merits (the raw reinforcement / undermining values from the latest
  snapshot) are used as the cycle baseline.  One PP cycle = 7 days, so:

      daily_deficit = (undermining - reinforcement) / 7

  progress is normalised to [0, 1] per cycle (0 = downgrade threshold,
  1 = upgrade threshold).  Days-to-failure is therefore:

      days_to_failure = progress * 7 / (undermining - reinforcement)

  A system with progress ≤ 0 is ALREADY failing — days_to_failure = 0.
  A system with net R ≥ U has no imminent failure — days_to_failure = None.

FORTIFY PRIORITY ORDER:
  1. progress ≤ 0   → CRITICAL — downgrade happening NOW (score = 1000 base)
  2. days_to_failure < 2 → URGENT — will fail within 2 days
  3. days_to_failure < 5 → WARNING — will fail within 5 days
  4. progress close to 1.0 and net positive → PROMOTE SOON (fortify bonus for upgrade)
  5. progress ≥ 1.0 AND state already Stronghold → SKIP (no action needed)

EXPAND PRIORITY ORDER:
  1. Unoccupied systems close to our controlled territory
  2. Higher control_progress Unoccupied = more "primed" for takeover
  3. Allegiance match = easier to flip
"""

from __future__ import annotations

import math
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.models import AdminSetting, PPSystem, PPSystemSnapshot
from models.schemas import RecommendationItem

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Scoring weights  (all adjustable via Admin panel → admin_settings table)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULTS: dict[str, float] = {
    # ── Fortify ──────────────────────────────────────────────────────────────
    # Urgency score = base * weight  (base is 0–1000 from the urgency model)
    "fortify_weight":             1.0,    # global fortify multiplier
    "fortify_near_center":        15.0,   # bonus if within 15 LY of center system

    # ── Expand ───────────────────────────────────────────────────────────────
    "expand_unoccupied":          60.0,   # base score for Unoccupied system
    "expand_high_progress":       30.0,   # bonus if progress > 0.5 (primed)
    "expand_proximity":           25.0,   # within 20 LY of a controlled system
    "expand_allegiance_match":    15.0,   # allegiance matches power
}

# ──────────────────────────────────────────────────────────────────────────────
# Power allegiance map  (Spansh abbreviated names, confirmed July 2026)
# ──────────────────────────────────────────────────────────────────────────────

POWER_ALLEGIANCE: dict[str, str] = {
    "A. Lavigny-Duval": "Empire",
    "Aisling Duval":    "Empire",
    "Zemina Torval":    "Empire",
    "Denton Patreus":   "Empire",
    "Felicia Winters":  "Federation",
    "Jerome Archer":    "Federation",
    "Edmund Mahon":     "Alliance",
    "Nakato Kaine":     "Alliance",
    "Pranav Antal":     "Independent",
    "Li Yong-Rui":      "Independent",
    "Archon Delaine":   "Independent",
    "Yuri Grom":        "Independent",
}

# ──────────────────────────────────────────────────────────────────────────────
# Urgency model constants
# ──────────────────────────────────────────────────────────────────────────────

# PP cycle length in days (weekly reset)
CYCLE_DAYS = 7.0

# Score bands — used so the urgency score is human-readable (0–1000 range)
# rather than a raw 0–1 float.
SCORE_FAILING_NOW    = 1000.0   # progress ≤ 0 — state change happening this cycle
SCORE_URGENT         = 800.0    # < 2 days to failure
SCORE_WARNING        = 600.0    # < 5 days to failure
SCORE_MONITOR        = 300.0    # < full cycle, net negative
SCORE_UPGRADE_CLOSE  = 150.0    # within 20% of upgrade threshold (reinforce bonus)
SCORE_NEAR_UPGRADE   = 80.0     # between 20-40% of upgrade threshold


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────


def load_weights(db: Session) -> dict[str, float]:
    rows = db.query(AdminSetting).all()
    weights = dict(DEFAULTS)
    for row in rows:
        if row.key in weights:
            try:
                weights[row.key] = float(row.value)
            except (ValueError, TypeError):
                pass
    return weights


def _dist(ax: float, ay: float, az: float, bx: float, by: float, bz: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def get_latest_snapshots(db: Session) -> dict[int, dict]:
    """Return latest PP snapshot per pp_systems.id using DISTINCT ON."""
    rows = db.execute(text("""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress, snapshot_time
        FROM pp_system_snapshots
        ORDER BY system_id, snapshot_time DESC
    """)).mappings().all()
    return {row["system_id"]: dict(row) for row in rows}


def get_progress_trend(system_id: int, db: Session) -> tuple[str, Optional[float]]:
    """Return (trend_label, daily_net_change) from the last 3 snapshots.

    trend_label: 'worsening' | 'improving' | 'stable' | 'unknown'
    daily_net_change: estimated change in control_progress per day
                      (negative = losing ground, positive = gaining)
    """
    rows = db.execute(text("""
        SELECT control_progress, snapshot_time
        FROM pp_system_snapshots
        WHERE system_id = :sid
          AND control_progress IS NOT NULL
        ORDER BY snapshot_time DESC
        LIMIT 3
    """), {"sid": system_id}).all()

    if len(rows) < 2:
        return "unknown", None

    # Compute per-day change between consecutive snapshots
    deltas: list[float] = []
    for i in range(len(rows) - 1):
        t_new = rows[i].snapshot_time
        t_old = rows[i + 1].snapshot_time
        p_new = rows[i].control_progress
        p_old = rows[i + 1].control_progress
        if t_new and t_old and t_new != t_old:
            days = max((t_new - t_old).total_seconds() / 86400.0, 0.01)
            deltas.append((p_new - p_old) / days)

    if not deltas:
        return "unknown", None

    avg_daily = sum(deltas) / len(deltas)

    if len(rows) >= 2:
        # Most recent direction
        p_newest = rows[0].control_progress
        p_prev   = rows[1].control_progress
        if p_newest < p_prev - 0.01:
            trend = "worsening"
        elif p_newest > p_prev + 0.01:
            trend = "improving"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return trend, avg_daily


# ──────────────────────────────────────────────────────────────────────────────
# Core urgency calculation
# ──────────────────────────────────────────────────────────────────────────────


def _fortify_urgency(
    power_state: Optional[str],
    reinforcement: Optional[int],
    undermining: Optional[int],
    control_progress: Optional[float],
    trend: str,
    daily_delta: Optional[float],
) -> tuple[float, list[str], Optional[float]]:
    """Compute a fortify urgency score (0–1000+), reasons, and days_to_failure.

    Returns (score, reasons, days_to_failure).

    Score semantics:
      1000  = failing right now (progress ≤ 0)
      800+  = < 2 days to failure
      600+  = < 5 days to failure
      300+  = net negative, at risk this cycle
      150+  = healthy but close to upgrade threshold (reinforce bonus)
        0   = healthy, no action needed
      -1    = skip entirely (Stronghold, already maxed)
    """
    r   = reinforcement or 0
    u   = undermining   or 0
    p   = control_progress if control_progress is not None else 0.5
    net = r - u   # positive = reinforcement winning, negative = undermining winning

    score:   float      = 0.0
    reasons: list[str]  = []
    days_to_failure: Optional[float] = None

    # ── 1. Stronghold: already at max defense ──────────────────────────────
    if power_state == "Stronghold":
        # Only flag if in serious danger (progress very low) — unusual but possible
        if p <= 0.0:
            score = SCORE_FAILING_NOW
            reasons.append("⚠ Stronghold FAILING — reinforcement urgently needed!")
            days_to_failure = 0.0
            return score, reasons, days_to_failure
        elif p < 0.05:
            score = SCORE_URGENT
            reasons.append(f"Stronghold at risk of dropping to Fortified (progress {p:.1%})")
            days_to_failure = _estimate_days(p, net, r)
            return score, reasons, days_to_failure
        return -1.0, [], None   # healthy Stronghold — skip

    # ── 2. Failing now (progress ≤ 0) ─────────────────────────────────────
    if p <= 0.0:
        score = SCORE_FAILING_NOW
        days_to_failure = 0.0
        state_desc = {
            "Exploited":  "losing this system to Unoccupied",
            "Fortified":  "dropping to Exploited",
        }.get(power_state or "", "losing current state")
        reasons.append(f"🚨 CRITICAL: {state_desc} — progress at {p:.1%}")
        if u > r:
            reasons.append(f"Undermining exceeds reinforcement by {u - r:,} this cycle")
        return score, reasons, days_to_failure

    # ── 3. Estimate days to failure based on net rate ──────────────────────
    days_to_failure = _estimate_days(p, net, r)

    if days_to_failure is not None and days_to_failure < 2.0:
        score = SCORE_URGENT
        reasons.append(
            f"⚠ URGENT: ~{days_to_failure:.1f} day{'s' if days_to_failure >= 1 else ''} "
            f"to state downgrade (progress {p:.1%})"
        )
    elif days_to_failure is not None and days_to_failure < 5.0:
        score = SCORE_WARNING
        reasons.append(
            f"⚠ WARNING: ~{days_to_failure:.1f} days to state downgrade "
            f"(progress {p:.1%})"
        )
    elif net < 0:
        # Net negative but not imminent — still worth monitoring
        score = SCORE_MONITOR
        reasons.append(
            f"Net negative this cycle (U={u:,} R={r:,} net={net:+,}) "
            f"— progress {p:.1%}"
        )
    else:
        # ── 4. Healthy — check if close to upgrade threshold ──────────────
        remaining_to_upgrade = 1.0 - p
        if remaining_to_upgrade <= 0.0:
            # Already past upgrade threshold — suppress (will upgrade naturally)
            return -1.0, [], None
        elif remaining_to_upgrade <= 0.20:
            score = SCORE_UPGRADE_CLOSE
            reasons.append(
                f"Nearly at {_next_state(power_state)} threshold "
                f"({p:.1%} / 100%) — push it over!"
            )
        elif remaining_to_upgrade <= 0.40:
            score = SCORE_NEAR_UPGRADE
            reasons.append(
                f"Approaching {_next_state(power_state)} threshold "
                f"({p:.1%} / 100%)"
            )
        else:
            # Healthy, no action needed
            return 0.0, [], None

    # ── 5. Trend modifier ─────────────────────────────────────────────────
    if trend == "worsening" and score > 0:
        score *= 1.20
        reasons.append("Trend: situation is getting worse over time")
    elif trend == "improving" and score < SCORE_URGENT:
        score *= 0.80
        reasons.append("Trend: situation is improving")

    return score, reasons, days_to_failure


def _estimate_days(
    progress: float,
    net_rein_minus_und: int,
    reinforcement: int = 0,  # kept for signature compatibility; unused after refactor
) -> Optional[float]:
    """Estimate days until progress reaches 0.0 given the current net rate.

    Uses Current Merits (the raw reinforcement / undermining snapshot values)
    as the baseline.  The weekly cycle is 7 days, so:

        daily_deficit = (undermining - reinforcement) / 7

    The progress field is already normalised to [0, 1] per cycle where 0 = at
    downgrade threshold and 1 = at upgrade threshold.  Therefore:

        days_to_failure = progress / (daily_deficit / total_range)

    Because progress is already a fraction of the full range we simplify to:

        days_to_failure = progress * 7 / (undermining - reinforcement)

    This directly uses the current snapshot merits as the rate basis.

    Returns None if the system is net-positive (reinforcement winning).
    Returns 0.0 if already at or past the downgrade threshold.
    """
    if progress <= 0.0:
        return 0.0
    if net_rein_minus_und >= 0:
        return None   # reinforcement is winning — no failure imminent

    # deficit = how much undermining exceeds reinforcement this cycle
    deficit = abs(net_rein_minus_und)   # > 0 because net is negative
    if deficit <= 0:
        return None

    # Daily rate: assume the current snapshot represents one full 7-day cycle.
    # days_to_failure = progress * CYCLE_DAYS / deficit  (simplified from above)
    return (progress * CYCLE_DAYS) / deficit


def _next_state(power_state: Optional[str]) -> str:
    return {"Exploited": "Fortified", "Fortified": "Stronghold"}.get(power_state or "", "next level")


# ──────────────────────────────────────────────────────────────────────────────
# Fortify scoring  (public entry point)
# ──────────────────────────────────────────────────────────────────────────────


def compute_fortify_scores(
    power_name: str,
    center_coords: Optional[tuple[float, float, float]],
    power_systems: list[PPSystem],
    snapshots: dict[int, dict],
    db: Session,
    weights: dict[str, float],
) -> list[RecommendationItem]:
    items: list[RecommendationItem] = []
    fw = weights.get("fortify_weight", 1.0)

    for system in power_systems:
        snap              = snapshots.get(system.id, {})
        power_state       = snap.get("power_state")
        reinforcement     = snap.get("reinforcement")
        undermining       = snap.get("undermining")
        control_progress  = snap.get("control_progress")

        trend, daily_delta = get_progress_trend(system.id, db)

        raw_score, reasons, days_to_failure = _fortify_urgency(
            power_state, reinforcement, undermining, control_progress, trend, daily_delta
        )

        if raw_score <= 0:
            continue   # healthy or skip

        score = raw_score * fw

        # Distance bonus
        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0
        distance_from_center: Optional[float] = None
        if center_coords is not None:
            cx, cy, cz = center_coords
            distance_from_center = _dist(sx, sy, sz, cx, cy, cz)
            if distance_from_center < 15.0:
                score += weights["fortify_near_center"]
                reasons.append(f"Close to center system ({distance_from_center:.1f} LY)")

        r = reinforcement or 0
        u = undermining   or 0
        undermine_ratio: Optional[float] = (u / r) if r > 0 else None

        items.append(RecommendationItem(
            system_id64=system.system_id64,
            system_name=system.name,
            score=round(score, 1),
            type="fortify",
            reasons=reasons,
            power_state=power_state,
            reinforcement=reinforcement,
            undermining=undermining,
            undermine_ratio=undermine_ratio,
            control_progress=control_progress,
            days_to_failure=days_to_failure,
            distance_from_center=distance_from_center,
            threat_trend=trend,
        ))

    items.sort(key=lambda x: x.score, reverse=True)
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Expand scoring
# ──────────────────────────────────────────────────────────────────────────────


def compute_expand_scores(
    power_name: str,
    center_coords: Optional[tuple[float, float, float]],
    power_systems: list[PPSystem],
    snapshots: dict[int, dict],
    db: Session,
    weights: dict[str, float],
) -> list[RecommendationItem]:
    """Score Unoccupied systems near this power's territory for expansion."""
    if not power_systems:
        return []

    power_coords      = [(s.x or 0.0, s.y or 0.0, s.z or 0.0) for s in power_systems]
    power_system_ids  = {s.id for s in power_systems}
    power_allegiance  = POWER_ALLEGIANCE.get(power_name)

    # Bounding box pre-filter: 30 LY around any controlled system
    all_x = [c[0] for c in power_coords]
    all_y = [c[1] for c in power_coords]
    all_z = [c[2] for c in power_coords]
    candidates: list[PPSystem] = db.query(PPSystem).filter(
        PPSystem.x.between(min(all_x) - 30.0, max(all_x) + 30.0),
        PPSystem.y.between(min(all_y) - 30.0, max(all_y) + 30.0),
        PPSystem.z.between(min(all_z) - 30.0, max(all_z) + 30.0),
        PPSystem.id.notin_(power_system_ids),
    ).all()

    items: list[RecommendationItem] = []

    for system in candidates:
        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0
        min_dist = min(_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in power_coords)
        if min_dist > 30.0:
            continue

        snap             = snapshots.get(system.id, {})
        power_state      = snap.get("power_state")
        current_power    = snap.get("power")
        control_progress = snap.get("control_progress") or 0.0

        if power_state != "Unoccupied" and current_power:
            continue   # skip systems controlled by another power

        score: float = 0.0
        reasons: list[str] = []

        if power_state == "Unoccupied":
            score += weights["expand_unoccupied"]
            reasons.append("System is Unoccupied — no controlling power")

        if control_progress > 0.5:
            score += weights["expand_high_progress"]
            reasons.append(f"High PP activity in this system (progress {control_progress:.1%})")

        if min_dist < 20.0:
            score += weights["expand_proximity"]
            reasons.append(f"Close to controlled system ({min_dist:.1f} LY)")

        if power_allegiance and system.allegiance == power_allegiance:
            score += weights["expand_allegiance_match"]
            reasons.append(f"{system.allegiance} allegiance matches power")

        if score <= 0:
            continue

        distance_from_center: Optional[float] = None
        if center_coords is not None:
            cx2, cy2, cz2 = center_coords
            distance_from_center = _dist(sx, sy, sz, cx2, cy2, cz2)

        items.append(RecommendationItem(
            system_id64=system.system_id64,
            system_name=system.name,
            score=round(score, 1),
            type="expand",
            reasons=reasons,
            power_state=power_state,
            control_progress=control_progress,
            distance_from_center=distance_from_center,
            threat_trend="unknown",
        ))

    items.sort(key=lambda x: x.score, reverse=True)
    return items[:20]


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────


def compute_recommendations(
    power_name: str,
    center_system_id64: Optional[int],
    db: Session,
) -> dict:
    import os

    weights   = load_weights(db)
    snapshots = get_latest_snapshots(db)

    powered_system_ids = {
        sid for sid, snap in snapshots.items()
        if snap.get("power") == power_name
    }
    if not powered_system_ids:
        return {"fortify": [], "expand": [], "llm_summary": None}

    power_systems = db.query(PPSystem).filter(PPSystem.id.in_(powered_system_ids)).all()

    center_coords: Optional[tuple[float, float, float]] = None
    center_name:   Optional[str] = None
    if center_system_id64 is not None:
        center_sys = db.query(PPSystem).filter(
            PPSystem.system_id64 == center_system_id64
        ).first()
        if center_sys:
            center_coords = (center_sys.x or 0.0, center_sys.y or 0.0, center_sys.z or 0.0)
            center_name   = center_sys.name

    fortify = compute_fortify_scores(power_name, center_coords, power_systems, snapshots, db, weights)
    expand  = compute_expand_scores(power_name, center_coords, power_systems, snapshots, db, weights)

    result: dict = {
        "fortify": fortify[:20],
        "expand":  expand[:20],
        "llm_summary": None,
    }

    if os.getenv("LLM_ENABLED", "false").lower() == "true":
        try:
            from ai.factory import get_provider
            provider = get_provider()
            result["llm_summary"] = provider.summarize_recommendations(
                power_name, center_name,
                [i.model_dump() for i in fortify[:5]],
                [i.model_dump() for i in expand[:5]],
            )
        except Exception as exc:
            logger.warning("LLM summary failed: %s", exc)

    return result
