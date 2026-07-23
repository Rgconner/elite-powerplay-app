"""Power Play 2.0 recommendation scoring engine.

═══════════════════════════════════════════════════════════════
PP 2.0 MECHANICS (confirmed from live Spansh API data, July 2026)
═══════════════════════════════════════════════════════════════

Actual states in the wild:   Exploited | Fortified | Stronghold | Unoccupied
Fields per system:
  power_state_reinforcement    (int)   — total reinforcement merits delivered this cycle
  power_state_undermining      (int)   — total undermining merits delivered this cycle
  power_state_control_progress (float) — normalised position within the current state band:
      < 0.0  → system is past the downgrade threshold (losing state THIS cycle)
      0.0–1.0 → safe range between downgrade and upgrade thresholds
      ≥ 1.0  → upgrade threshold crossed (state upgrade imminent)

ABSOLUTE MERIT THRESHOLDS (confirmed game constants):
  Unoccupied  → Exploited  (Acquire)   :    120,000 merits  cumulative
  Exploited   → Fortified              :    333,000 merits  cumulative
  Fortified   → Stronghold             :    667,000 merits  cumulative

  Band widths:
    Exploited  band = 333,000 − 120,000 = 213,000 merits
    Fortified  band = 667,000 − 333,000 = 334,000 merits
    Stronghold band = open-ended (using 334,000 as proxy for rate calculations)

  From these, given progress p and state:
    merit_position   = lower_threshold + (p × band_width)
    buffer_merits    = p × band_width          (merits above downgrade threshold)
    merits_to_safety = (0.5 − p) × band_width  (merits to reach 50% — safe zone)
    merits_to_upgrade= (1.0 − p) × band_width  (merits to reach next state)

STATE TRANSITIONS:
  Exploited  → Unoccupied if progress ≤ 0.0 (drops below 120,000 cumulative)
  Fortified  → Exploited  if progress ≤ 0.0 (drops below 333,000 cumulative)
  Stronghold → Fortified  if progress ≤ 0.0 (drops below 667,000 cumulative)
  Exploited  → Fortified  if progress ≥ 1.0
  Fortified  → Stronghold if progress ≥ 1.0

DAYS-TO-FAILURE (correct formula, verified against HR 943 live data):
  buffer_merits   = progress × band_width   (absolute merits above downgrade threshold)
  daily_net_loss  = undermining − reinforcement   (current snapshot as daily-rate proxy)
  days_to_failure = buffer_merits / daily_net_loss

  Example — HR 943 (R=36, U=525, progress=0.2666, Exploited, band=213,000):
    buffer  = 0.2666 × 213,000 = 56,786 merits
    net     = 525 − 36         = 489 merits/day loss
    days    = 56,786 / 489     = 116 days  → MONITOR band

  Returns 0.0  if progress ≤ 0 (buffer already exhausted — downgrade NOW)
  Returns None if R ≥ U        (gaining merits — no failure risk)

  Additional merit context displayed to players:
    buffer_merits     = progress × band_width  (absolute cushion above downgrade)
    merits_to_safety  = (0.5 − p) × band_width (additional R needed to reach 50%)
    merits_to_upgrade = (1.0 − p) × band_width (R needed to reach next state)

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
from datetime import datetime, timezone, timedelta
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

    # ── Fortification alert thresholds (days-to-failure cutoffs) ─────────────
    # Each value is a number of DAYS.  When days_to_failure falls below the
    # threshold the corresponding urgency band fires.  Applies per power-state.
    # Default values mirror the hard-coded bands used before this was made
    # configurable: URGENT < 7d, WARNING < 21d (three full cycles).
    "exploited_threshold_critical":  0.0,   # progress ≤ 0 → already failing (not days-based)
    "exploited_threshold_urgent":    7.0,   # days_to_failure < this → URGENT
    "exploited_threshold_warning":  21.0,   # days_to_failure < this → WARNING
    "fortified_threshold_critical":  0.0,
    "fortified_threshold_urgent":    7.0,
    "fortified_threshold_warning":  21.0,
    "stronghold_threshold_critical": 0.0,
    "stronghold_threshold_urgent":   7.0,
    "stronghold_threshold_warning":  21.0,

    # ── Expand ───────────────────────────────────────────────────────────────
    "expand_allegiance_match":    15.0,   # allegiance matches power bonus
    # Proximity thresholds: Unoccupied must be within these distances of an
    # anchor system of the specified state to qualify as an expansion target.
    "expand_fortified_dist_ly":   20.0,   # max LY from a Fortified anchor
    "expand_stronghold_dist_ly":  30.0,   # max LY from a Stronghold anchor

    # ── Target Analysis ───────────────────────────────────────────────────────
    # Base vulnerability scores per enemy state tier
    "target_score_stronghold":   1000.0,  # Stronghold — highest value undermine target
    "target_score_fortified":     600.0,  # Fortified
    "target_score_exploited":     200.0,  # Exploited — lowest tier
    "target_score_contested":     800.0,  # Contested — our power making progress here
    # Progress bonus: adds up to this many points when enemy progress near 0
    "target_progress_bonus_max":  300.0,
    # Proximity bonus: adds up to this many points when ≤ target_dist_max_ly away
    "target_prox_bonus_max":      150.0,
    "target_dist_max_ly":          30.0,  # LY beyond which proximity bonus = 0
    # Max results returned by target-analysis endpoint
    "target_max_results":          50.0,  # stored as float; cast to int at use site
    # Progress thresholds for classifying enemy systems as vulnerable
    # (used by Target Analysis page to colour-code the progress bar)
    "target_progress_critical":    0.10,  # ≤ this % → CRITICAL (almost failing now)
    "target_progress_high":        0.25,  # ≤ this % → HIGH vulnerability
    "target_progress_medium":      0.50,  # ≤ this % → MEDIUM vulnerability
    # (above target_progress_medium → LOW)

    # ── Contested / Acquisition thresholds ────────────────────────────────────
    # Minimum control points (merits) required for a power to be considered
    # an active participant in a contested system. All powers below this
    # threshold are ignored when determining if a system is "truly" contested.
    "contested_min_control_points": 35000.0,

    # ── Staleness — NULL spansh_updated_at behaviour ──────────────────────────
    # When "true" (default): rows where spansh_updated_at IS NULL are treated
    # as stale and excluded from Contested queries (strictest / spec-correct).
    # Set to "false" to keep pre-migration rows (legacy behaviour for testing).
    # Toggled via the Admin panel checkbox — stored as "true" / "false" string.
    "contested_null_ts_is_stale": 1.0,   # 1 = true, 0 = false (stored as string in DB)
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
# Absolute merit thresholds (confirmed game constants)
# ──────────────────────────────────────────────────────────────────────────────

MERIT_ACQUIRE    = 120_000   # cumulative merits to acquire (Unoccupied → Exploited)
MERIT_FORTIFIED  = 333_000   # cumulative merits for Fortified
MERIT_STRONGHOLD = 667_000   # cumulative merits for Stronghold

# Band widths — merits between downgrade and upgrade thresholds per state
BAND_EXPLOITED   = MERIT_FORTIFIED  - MERIT_ACQUIRE    # 213,000
BAND_FORTIFIED   = MERIT_STRONGHOLD - MERIT_FORTIFIED  # 334,000
BAND_STRONGHOLD  = BAND_FORTIFIED                      # open-ended; use Fortified band as proxy

# ──────────────────────────────────────────────────────────────────────────────
# Urgency model constants
# ──────────────────────────────────────────────────────────────────────────────

# PP cycle length in days (weekly reset — every Thursday ~07:00 UTC)
CYCLE_DAYS = 7.0

# PP cycle reset: Thursday 07:00 UTC
_RESET_WEEKDAY = 3          # Monday=0 … Thursday=3
_RESET_HOUR_UTC = 7


def days_elapsed_in_cycle(reference_time: Optional[datetime] = None) -> float:
    """Return how many days have elapsed since the last PP Thursday reset.

    The PP cycle resets every Thursday at ~07:00 UTC.
    R and U values in a snapshot represent CUMULATIVE merits delivered since
    that reset — not a single day's activity.  Dividing by days_elapsed gives
    the true daily rate.

    Returns a float in [1.0, 7.0].  Minimum is 1.0 (reset day itself) to
    avoid division-by-zero and because at least one day of activity is implied
    by any non-zero merit values.
    """
    now = reference_time or datetime.now(timezone.utc)
    # Strip timezone for arithmetic if needed
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    # Find the most recent Thursday 07:00 UTC
    days_since = (now.weekday() - _RESET_WEEKDAY) % 7
    last_reset = now.replace(hour=_RESET_HOUR_UTC, minute=0, second=0, microsecond=0) \
                 - timedelta(days=days_since)

    # If today IS Thursday but before 07:00, go back one more week
    if last_reset > now:
        last_reset -= timedelta(days=7)

    elapsed = (now - last_reset).total_seconds() / 86400.0
    return max(1.0, min(elapsed, 7.0))

# Score bands — used so the urgency score is human-readable (0–1000 range)
# rather than a raw 0–1 float.
SCORE_FAILING_NOW    = 1000.0   # progress ≤ 0 — state change happening this cycle
SCORE_URGENT         = 800.0    # < 2 days to failure
SCORE_WARNING        = 600.0    # < 5 days to failure
SCORE_MONITOR        = 300.0    # < full cycle, net negative
SCORE_UPGRADE_CLOSE  = 150.0    # within 20% of upgrade threshold (reinforce bonus)
SCORE_NEAR_UPGRADE   = 80.0     # between 20-40% of upgrade threshold


def _band_width(power_state: Optional[str]) -> float:
    """Return the merit band width for a given power state."""
    return {
        "Exploited":  float(BAND_EXPLOITED),
        "Fortified":  float(BAND_FORTIFIED),
        "Stronghold": float(BAND_STRONGHOLD),
    }.get(power_state or "", float(BAND_EXPLOITED))


def _lower_threshold(power_state: Optional[str]) -> int:
    """Return the absolute lower merit threshold (downgrade boundary) for a state."""
    return {
        "Exploited":  MERIT_ACQUIRE,
        "Fortified":  MERIT_FORTIFIED,
        "Stronghold": MERIT_STRONGHOLD,
    }.get(power_state or "", MERIT_ACQUIRE)


def _merit_fields(
    power_state: Optional[str],
    progress: float,
) -> dict:
    """Compute absolute merit context fields from progress + state.

    Returns a dict with:
      merit_position    — absolute position on the 0→667k merit scale
      buffer_merits     — merits above downgrade threshold (cushion)
      merits_to_safety  — additional merits needed to reach 50% progress (safe zone)
      merits_to_upgrade — additional merits needed to reach 100% (next state)
    """
    band  = _band_width(power_state)
    lower = _lower_threshold(power_state)
    p     = max(0.0, progress)   # clamp for display (don't show negative buffer)

    buffer          = p * band
    merit_position  = lower + buffer
    to_safety       = max(0.0, (0.5 - p) * band)
    to_upgrade      = max(0.0, (1.0 - p) * band)

    return {
        "merit_position":    round(merit_position),
        "buffer_merits":     round(buffer),
        "merits_to_safety":  round(to_safety),
        "merits_to_upgrade": round(to_upgrade),
    }


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
    """Return latest PP snapshot per pp_systems.id using DISTINCT ON.

    Staleness filter: exclude snapshots where Spansh's own updated_at is older
    than 7 days.  This prevents resolved systems (e.g. a formerly-contested
    system that is now Exploited) from appearing stale in recommendations.

    Rows with NULL spansh_updated_at are only kept if their snapshot_time
    is also recent (within 7 days), so pre-migration rows eventually age out
    instead of persisting forever.
    """
    rows = db.execute(text("""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress,
               snapshot_time, spansh_updated_at,
               conflict_progress,
               cp_decay
        FROM pp_system_snapshots
        WHERE (
            spansh_updated_at > NOW() - INTERVAL '7 days'
            OR (
                spansh_updated_at IS NULL
                AND snapshot_time > NOW() - INTERVAL '7 days'
            )
        )
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
    snapshot_time: Optional[datetime] = None,
    weights: Optional[dict] = None,
) -> tuple[float, list[str], Optional[float]]:
    """Compute a fortify urgency score (0–1000+), reasons, and days_to_failure.

    Returns (score, reasons, days_to_failure).

    KEY RULE: urgency is ONLY triggered when undermining > reinforcement (net < 0).
      A system with R >= U has no threat regardless of how low progress is.
      Low progress + no undermining = normal state, no action needed.

    days_to_failure = buffer_merits / (U - R)   [only computed when U > R]
      where buffer_merits = progress × band_width

    Urgency bands (thresholds configurable via weights / Admin panel):
      CRITICAL  (1000) : progress ≤ 0          — downgrade happening NOW
      URGENT    ( 800) : days < urgent_threshold  (default 7d)
      WARNING   ( 600) : days < warning_threshold (default 21d)
      MONITOR   ( 300) : net negative, days ≥ warning_threshold
      UPGRADE   ( 150) : net positive, within 20% of upgrade threshold
        0              : healthy, no action needed
       -1              : skip (Stronghold with no threat, or already maxed)
    """
    r   = reinforcement or 0
    u   = undermining   or 0
    p   = control_progress if control_progress is not None else 0.5
    net = r - u   # positive = R winning, negative = U winning

    score:   float      = 0.0
    reasons: list[str]  = []
    days_to_failure: Optional[float] = None

    # Pre-compute absolute merit context for inclusion in reasons
    mf = _merit_fields(power_state, p)

    # ── Resolve per-state day thresholds ──────────────────────────────────
    w = weights or {}
    state_key = (power_state or "exploited").lower()
    urgent_days  = float(w.get(f"{state_key}_threshold_urgent",  DEFAULTS.get(f"{state_key}_threshold_urgent",  7.0)))
    warning_days = float(w.get(f"{state_key}_threshold_warning", DEFAULTS.get(f"{state_key}_threshold_warning", 21.0)))

    # ── 1. Stronghold ──────────────────────────────────────────────────────
    # Stronghold is the highest state — only flag if ACTIVELY being undermined.
    # Low progress alone is NOT a threat if nobody is undermining.
    if power_state == "Stronghold":
        if p <= 0.0 and u > r:
            # Actively failing AND being undermined
            score = SCORE_FAILING_NOW
            reasons.append("⚠ Stronghold FAILING — reinforcement urgently needed!")
            reasons.append(f"Merit position: {mf['merit_position']:,} (below {MERIT_STRONGHOLD:,} threshold)")
            days_to_failure = 0.0
            return score, reasons, days_to_failure
        elif p <= 0.0:
            # Progress exhausted but no active undermining — watch only
            score = SCORE_MONITOR
            reasons.append(f"Stronghold progress at {p:.1%} — no active undermining but buffer exhausted")
            reasons.append(f"Buffer: {mf['buffer_merits']:,} merits · Need {mf['merits_to_safety']:,} to reach safety")
            return score, reasons, days_to_failure
        elif u > r:
            # Being undermined — compute days using buffer/net formula
            days_to_failure = _estimate_days(p, power_state, r, u, snapshot_time)
            if days_to_failure is not None and days_to_failure < urgent_days:
                score = SCORE_URGENT
                reasons.append(f"⚠ Stronghold under active attack — ~{days_to_failure:.1f}d to drop to Fortified")
            elif days_to_failure is not None and days_to_failure < warning_days:
                score = SCORE_WARNING
                reasons.append(f"⚠ Stronghold being undermined — ~{days_to_failure:.1f}d to drop to Fortified")
            else:
                score = SCORE_MONITOR
                d_str = f"~{days_to_failure:.0f}d" if days_to_failure is not None else "unknown"
                reasons.append(f"Stronghold under minor pressure ({d_str} at current rate)")
            reasons.append(f"Buffer: {mf['buffer_merits']:,} merits · Net: {net:+,}/day · Need {mf['merits_to_safety']:,} to safety")
            return score, reasons, days_to_failure
        else:
            # Stronghold, healthy, no threat — skip entirely
            return -1.0, [], None

    # ── 2. Failing now (progress ≤ 0) ─────────────────────────────────────
    if p <= 0.0:
        if u <= r:
            # Progress is at zero but not being actively undermined — monitor only
            score = SCORE_MONITOR
            state_desc = {
                "Exploited": "at Unoccupied boundary",
                "Fortified": "at Exploited boundary",
            }.get(power_state or "", "at downgrade boundary")
            reasons.append(f"Progress at {p:.1%} ({state_desc}) — no active undermining")
            reasons.append(f"Buffer: {mf['buffer_merits']:,} merits — reinforce to rebuild cushion")
            return score, reasons, days_to_failure
        # Actively failing with U > R
        score = SCORE_FAILING_NOW
        days_to_failure = 0.0
        state_desc = {
            "Exploited": "losing this system to Unoccupied",
            "Fortified": "dropping to Exploited",
        }.get(power_state or "", "losing current state")
        reasons.append(f"🚨 CRITICAL: {state_desc} — progress at {p:.1%}")
        reasons.append(f"Undermining exceeds reinforcement by {u - r:,} this cycle")
        reasons.append(f"Need {mf['merits_to_safety']:,} merits to reach safety · {mf['merits_to_upgrade']:,} to upgrade")
        return score, reasons, days_to_failure

    # ── 3. Estimate days to failure: buffer / daily_rate ──────────────────
    # _estimate_days returns None when R >= U — system is not threatened
    days_to_failure = _estimate_days(p, power_state, r, u, snapshot_time)

    if days_to_failure is not None and days_to_failure < urgent_days:
        # U > R AND buffer runs out within urgent threshold
        elapsed = days_elapsed_in_cycle(snapshot_time)
        score = SCORE_URGENT
        reasons.append(
            f"⚠ URGENT: ~{days_to_failure:.1f} day{'s' if days_to_failure >= 1 else ''} "
            f"to state downgrade at current rate"
        )
        reasons.append(
            f"Buffer: {mf['buffer_merits']:,} merits · Cycle net: {u-r:,} over {elapsed:.1f}d "
            f"({(u-r)/elapsed:.0f}/day) · Need {mf['merits_to_safety']:,} to safety"
        )
    elif days_to_failure is not None and days_to_failure < warning_days:
        # U > R AND buffer runs out within warning threshold
        elapsed = days_elapsed_in_cycle(snapshot_time)
        score = SCORE_WARNING
        reasons.append(
            f"⚠ WARNING: ~{days_to_failure:.1f} days to state downgrade at current rate"
        )
        reasons.append(
            f"Buffer: {mf['buffer_merits']:,} merits · Cycle net: {u-r:,} over {elapsed:.1f}d "
            f"({(u-r)/elapsed:.0f}/day) · Need {mf['merits_to_safety']:,} to safety"
        )
    elif days_to_failure is not None:
        # U > R but large buffer — monitor
        elapsed = days_elapsed_in_cycle(snapshot_time)
        score = SCORE_MONITOR
        reasons.append(
            f"Under pressure — ~{days_to_failure:.0f}d at current rate "
            f"(U={u:,} R={r:,} · {elapsed:.1f}d into cycle · {(u-r)/elapsed:.0f}/day net loss)"
        )
        reasons.append(f"Buffer: {mf['buffer_merits']:,} merits · Need {mf['merits_to_safety']:,} to reach safety")
    else:
        # days_to_failure is None → R >= U → no active threat
        # ── 4. Healthy — check if close to upgrade threshold ──────────────
        remaining_to_upgrade = 1.0 - p
        if remaining_to_upgrade <= 0.0:
            return -1.0, [], None   # already past upgrade threshold
        elif remaining_to_upgrade <= 0.20:
            score = SCORE_UPGRADE_CLOSE
            reasons.append(
                f"Nearly at {_next_state(power_state)} threshold "
                f"({p:.1%} / 100%) — push it over!"
            )
            reasons.append(f"Only {mf['merits_to_upgrade']:,} more merits needed to upgrade")
        elif remaining_to_upgrade <= 0.40:
            score = SCORE_NEAR_UPGRADE
            reasons.append(
                f"Approaching {_next_state(power_state)} threshold ({p:.1%} / 100%)"
            )
            reasons.append(f"{mf['merits_to_upgrade']:,} merits needed to upgrade")
        else:
            return 0.0, [], None   # healthy, no action needed

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
    power_state: Optional[str],
    reinforcement: int,
    undermining: int,
    snapshot_time: Optional[datetime] = None,
) -> Optional[float]:
    """Estimate days until the system's merit buffer is exhausted.

    The R and U values in a Spansh snapshot are CUMULATIVE since the last
    Thursday 07:00 UTC PP reset — NOT a single day's activity.  To get the
    true daily loss rate we divide by the number of days elapsed since reset.

    Formula:
        buffer_merits    = progress × band_width
        days_elapsed     = days since last Thursday 07:00 UTC  (1.0–7.0)
        daily_net_loss   = (undermining − reinforcement) / days_elapsed
        days_to_failure  = buffer_merits / daily_net_loss

    Example — HR 943 on Saturday (2 days since Thursday reset):
        buffer        = 0.2666 × 213,000 = 56,786 merits
        cycle net     = 525 − 36         = 489 merits over 2 days
        daily rate    = 489 / 2          = 244.5 merits/day
        days_failure  = 56,786 / 244.5   = 232 days

    Returns 0.0 if already at or past downgrade threshold (progress ≤ 0).
    Returns None if reinforcement ≥ undermining (not losing ground).
    """
    if progress <= 0.0:
        return 0.0

    net_loss_cycle = undermining - reinforcement   # total this cycle; positive = losing
    if net_loss_cycle <= 0:
        return None   # reinforcement winning — no failure imminent

    # Divide cumulative cycle merits by days elapsed to get true daily rate
    elapsed = days_elapsed_in_cycle(snapshot_time)
    daily_net_loss = net_loss_cycle / elapsed

    buffer = progress * _band_width(power_state)
    return buffer / daily_net_loss


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
        snapshot_time     = snap.get("snapshot_time")   # datetime of the snapshot
        cp_decay_val      = snap.get("cp_decay")

        trend, daily_delta = get_progress_trend(system.id, db)

        raw_score, reasons, days_to_failure = _fortify_urgency(
            power_state, reinforcement, undermining, control_progress,
            trend, daily_delta, snapshot_time, weights,
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

        from services.decay import effective_undermining as _eff_u
        r = reinforcement or 0
        u = undermining   or 0
        eff_u = _eff_u(u, cp_decay_val)
        undermine_ratio: Optional[float] = (eff_u / r) if r > 0 else None

        # Absolute merit context
        p_val = control_progress if control_progress is not None else 0.5
        mf = _merit_fields(power_state, p_val)

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
            merit_position=mf["merit_position"],
            buffer_merits=mf["buffer_merits"],
            merits_to_safety=mf["merits_to_safety"],
            merits_to_upgrade=mf["merits_to_upgrade"],
            cp_decay=cp_decay_val,
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
    """Score Unoccupied systems for expansion priority.

    Spansh ONLY uses power_state='Unoccupied' for ALL expansion-stage systems,
    including those being actively fought over by multiple powers.  There is no
    'Expansion' state in the Spansh API.

    Eligibility rules:
      • power_state = 'Unoccupied' with 1 power in powers_list (solo push):
          requires proximity to a Fortified/Stronghold anchor
          (within expand_fortified_dist_ly / expand_stronghold_dist_ly).
      • power_state = 'Unoccupied' with 2+ powers in powers_list (contested expansion):
          anchor proximity check is skipped — already has multi-power activity.
          The selected power must appear in powers_list.

    Primary ranking: closeness to the 120,000-merit acquisition threshold.
      merit_position   = control_progress × MERIT_ACQUIRE
      score (0–100)    = merit_position / MERIT_ACQUIRE × 100

    Secondary tiebreak: allegiance match adds a small bonus.
    """
    if not power_systems:
        return []

    # ── Split anchor coords by state ────────────────────────────────────────
    fortified_coords:  list[tuple[float, float, float]] = []
    stronghold_coords: list[tuple[float, float, float]] = []
    for s in power_systems:
        state = snapshots.get(s.id, {}).get("power_state")
        coord = (s.x or 0.0, s.y or 0.0, s.z or 0.0)
        if state == "Fortified":
            fortified_coords.append(coord)
        elif state == "Stronghold":
            stronghold_coords.append(coord)

    power_coords     = [(s.x or 0.0, s.y or 0.0, s.z or 0.0) for s in power_systems]
    power_system_ids = {s.id for s in power_systems}
    power_allegiance = POWER_ALLEGIANCE.get(power_name)

    # ── Configurable distance thresholds ────────────────────────────────────
    fort_max = float(weights.get("expand_fortified_dist_ly",
                                  DEFAULTS["expand_fortified_dist_ly"]))
    sh_max   = float(weights.get("expand_stronghold_dist_ly",
                                  DEFAULTS["expand_stronghold_dist_ly"]))
    bbox_pad = max(fort_max, sh_max)

    # ── Fetch all Unoccupied systems where selected power appears ─────────────
    # Two categories in one query:
    #   a) systems where power matches directly (solo push, power = power_name)
    #   b) systems where power appears in powers_list with 2+ powers (contested push)
    # We fetch both via powers_list ILIKE and let the anchor gate below decide.
    # The bounding-box on pp_systems is used for (a); for (b) we do a direct DB
    # query because the system may not be near the selected power's territory.
    _STALE = """
        AND (
            spansh_updated_at > NOW() - INTERVAL '7 days'
            OR (spansh_updated_at IS NULL AND snapshot_time > NOW() - INTERVAL '7 days')
        )
    """

    # Contested-expansion: Unoccupied + 2 or more powers + selected power present.
    # Stored during ingest with power_state='Contested' (our internal label) and
    # powers_list = comma-separated list of all contesting powers.
    # Filter: selected power + at least 1 other must have ≥ MIN_CP control points.
    MIN_CP = int(weights.get("contested_min_control_points", DEFAULTS.get("contested_min_control_points", 35000)))
    contested_exp_rows = db.execute(text(f"""
        SELECT DISTINCT ON (system_id)
               system_id, power, power_state,
               reinforcement, undermining, control_progress,
               snapshot_time, spansh_updated_at, conflict_progress,
               powers_list
        FROM pp_system_snapshots
        WHERE power_state IN ('Contested', 'Acquisition')
          AND powers_list ILIKE :pattern
          {_STALE}
        ORDER BY system_id, snapshot_time DESC
    """), {"pattern": f"%{power_name}%"}).mappings().all()

    # Apply 35k threshold filter in Python
    import json as _json
    contested_exp_sys_ids = []
    contested_exp_snaps   = {}
    for r in contested_exp_rows:
        cp_str = r.get("conflict_progress") or ""
        qualifying: list[str] = []
        if cp_str:
            try:
                for entry in _json.loads(cp_str):
                    if isinstance(entry, dict) and (entry.get("progress") or 0) >= MIN_CP:
                        qualifying.append(entry.get("power", ""))
            except Exception:
                pass
        if power_name in qualifying and len(qualifying) >= 2:
            contested_exp_sys_ids.append(r["system_id"])
            contested_exp_snaps[r["system_id"]] = dict(r)
    contested_exp_objs    = {s.id: s for s in (
        db.query(PPSystem).filter(PPSystem.id.in_(contested_exp_sys_ids)).all()
        if contested_exp_sys_ids else []
    )}

    # Solo-expansion: bounding-box candidates where snapshot power = power_name
    # and power_state = 'Unoccupied' (single power pushing).
    all_x = [c[0] for c in power_coords]
    all_y = [c[1] for c in power_coords]
    all_z = [c[2] for c in power_coords]
    solo_candidates: list[PPSystem] = db.query(PPSystem).filter(
        PPSystem.x.between(min(all_x) - bbox_pad, max(all_x) + bbox_pad),
        PPSystem.y.between(min(all_y) - bbox_pad, max(all_y) + bbox_pad),
        PPSystem.z.between(min(all_z) - bbox_pad, max(all_z) + bbox_pad),
        PPSystem.id.notin_(power_system_ids),
        PPSystem.id.notin_(contested_exp_sys_ids),  # don't double-count
    ).all()

    # ── Build unified (system, snap, is_contested_expansion) list ────────────
    scored_candidates: list[tuple[PPSystem, dict, bool]] = []

    for sid, snap in contested_exp_snaps.items():
        system = contested_exp_objs.get(sid)
        if system is not None:
            scored_candidates.append((system, snap, True))

    for system in solo_candidates:
        snap = snapshots.get(system.id)
        if snap is None:
            continue
        if snap.get("power_state") != "Unoccupied":
            continue
        # Must be this power's solo push
        if snap.get("power") != power_name:
            continue
        sx, sy, sz = system.x or 0.0, system.y or 0.0, system.z or 0.0
        dist_fort = min(
            (_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in fortified_coords),
            default=9_999.0,
        )
        dist_sh = min(
            (_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in stronghold_coords),
            default=9_999.0,
        )
        if dist_fort <= fort_max or dist_sh <= sh_max:
            scored_candidates.append((system, snap, False))

    items: list[RecommendationItem] = []

    for system, snap, is_contested_exp in scored_candidates:
        sx, sy, sz  = system.x or 0.0, system.y or 0.0, system.z or 0.0
        power_state = snap.get("power_state", "Unoccupied")

        if is_contested_exp:
            in_fort_range = False
            in_sh_range   = False
            dist_fort     = 9_999.0
            dist_sh       = 9_999.0
        else:
            dist_fort = min(
                (_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in fortified_coords),
                default=9_999.0,
            )
            dist_sh = min(
                (_dist(sx, sy, sz, cx, cy, cz) for cx, cy, cz in stronghold_coords),
                default=9_999.0,
            )
            in_fort_range = dist_fort <= fort_max
            in_sh_range   = dist_sh   <= sh_max

        # ── Merit-proximity score (0–100 scale) ─────────────────────────────
        progress    = float(snap.get("control_progress") or 0.0)
        merit_pos   = round(progress * MERIT_ACQUIRE)
        merits_left = max(0, MERIT_ACQUIRE - merit_pos)
        score       = round((merit_pos / MERIT_ACQUIRE) * 100.0, 2)

        # ── Allegiance tiebreak ──────────────────────────────────────────────
        if power_allegiance and system.allegiance == power_allegiance:
            score += float(weights.get("expand_allegiance_match",
                                       DEFAULTS["expand_allegiance_match"]))

        # ── Build reason list ────────────────────────────────────────────────
        reasons: list[str] = []
        if merit_pos == 0:
            reasons.append("No PP activity yet — needs 120,000 merits to acquire")
        elif merits_left == 0:
            reasons.append(f"🚀 Acquisition threshold reached ({merit_pos:,} merits) — claim now!")
        else:
            reasons.append(
                f"Acquisition progress: {progress:.1%} "
                f"({merit_pos:,} / {MERIT_ACQUIRE:,} merits)"
            )
            reasons.append(f"Merits still needed: {merits_left:,}")

        # ── Anchor / contested-expansion badge ──────────────────────────────
        if is_contested_exp:
            anchor_type = "expansion"
            reasons.append("Multi-power contested expansion — anchor check skipped")
        else:
            anchor_parts: list[str] = []
            if in_fort_range:
                anchor_parts.append(f"Fortified system {dist_fort:.1f} LY away")
            if in_sh_range:
                anchor_parts.append(f"Stronghold system {dist_sh:.1f} LY away")
            reasons.append("Anchor: " + " · ".join(anchor_parts))
            if in_fort_range and in_sh_range:
                anchor_type = "both"
            elif in_fort_range:
                anchor_type = "fortified"
            else:
                anchor_type = "stronghold"

        if power_allegiance and system.allegiance == power_allegiance:
            reasons.append(
                f"{system.allegiance} allegiance matches power "
                f"(+{weights.get('expand_allegiance_match', DEFAULTS['expand_allegiance_match']):.0f} pts)"
            )

        # ── Distance from reference system ───────────────────────────────────
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
            control_progress=progress,
            distance_from_center=distance_from_center,
            threat_trend="unknown",
            merit_position=merit_pos,
            buffer_merits=merit_pos,
            merits_to_safety=None,
            merits_to_upgrade=merits_left,
            anchor_type=anchor_type,
            conflict_progress=snap.get("conflict_progress"),
        ))

    # Sort: score descending (highest acquisition progress first)
    items.sort(key=lambda x: x.score, reverse=True)
    return items[:20]


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────


def compute_recommendations(
    power_name: str,
    ref_system_id64: Optional[int],     # reference system (formerly center_system_id64)
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
    if ref_system_id64 is not None:
        center_sys = db.query(PPSystem).filter(
            PPSystem.system_id64 == ref_system_id64
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
