"""Power Play merit decay calculation.

PP 2.0 introduces a "merit decay" mechanic: at the start of each cycle
(Thursday 07:00 UTC), a percentage of Control Points (CP) decays based on
the system's power state and control progress. This estimated decay is
subtracted from the undermining value to compute the "effective undermining"
and thus the true Net (R − U_eff).

Decay rates (linear interpolation):
  Below 25% progress: 0% decay (no decay at all)

  Stronghold:
    25.1% progress → 2.6% of CP
    100% progress  → 15.6% of CP  (linear between)

  Fortified:
    25.1% progress → 0.1% of CP
    89% progress   → 10.9% of CP  (extrapolated to 100%)

  Exploited:
    25.1% progress → 0.1% of CP
    89% progress   → 5.3% of CP   (extrapolated to 100%)

  Acquisition / Unoccupied / Contested: 0% decay

CP (Control Points) = absolute merit position:
  CP = lower_threshold + (progress × band_width)

CP_decay = CP × decay_rate
effective_undermining = max(0, undermining − CP_decay)

The decay is computed once per cycle per system and stored on the snapshot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Absolute merit thresholds (must match scoring.py)
# ──────────────────────────────────────────────────────────────────────────────

MERIT_ACQUIRE    = 120_000
MERIT_FORTIFIED  = 333_000
MERIT_STRONGHOLD = 667_000

BAND_EXPLOITED  = MERIT_FORTIFIED  - MERIT_ACQUIRE    # 213,000
BAND_FORTIFIED  = MERIT_STRONGHOLD - MERIT_FORTIFIED  # 334,000
BAND_STRONGHOLD = BAND_FORTIFIED                      # 334,000 (proxy)

# ──────────────────────────────────────────────────────────────────────────────
# Decay rate endpoints  (min_progress, min_rate, max_progress, max_rate)
# ──────────────────────────────────────────────────────────────────────────────

# Stronghold: 2.6% at 25.1% → 15.6% at 100%
_DECAY_STRONGHOLD = (0.251, 0.026, 1.0, 0.156)

# Fortified: 0.1% at 25.1% → 10.9% at 89%, extrapolated to 100%
# Slope = (0.109 - 0.001) / (0.89 - 0.251) = 0.108 / 0.639 = 0.16901
# At 100%: 0.001 + (1.0 - 0.251) × 0.16901 = 0.001 + 0.12657 = 0.12757
_FORT_SLOPE = (0.109 - 0.001) / (0.89 - 0.251)
_FORT_MAX_100 = 0.001 + (1.0 - 0.251) * _FORT_SLOPE
_DECAY_FORTIFIED = (0.251, 0.001, 1.0, round(_FORT_MAX_100, 6))

# Exploited: 0.1% at 25.1% → 5.3% at 89%, extrapolated to 100%
# Slope = (0.053 - 0.001) / (0.89 - 0.251) = 0.052 / 0.639 = 0.08138
# At 100%: 0.001 + (1.0 - 0.251) × 0.08138 = 0.001 + 0.06095 = 0.06195
_EXP_SLOPE = (0.053 - 0.001) / (0.89 - 0.251)
_EXP_MAX_100 = 0.001 + (1.0 - 0.251) * _EXP_SLOPE
_DECAY_EXPLOITED = (0.251, 0.001, 1.0, round(_EXP_MAX_100, 6))

# PP cycle reset: Thursday 07:00 UTC
_RESET_WEEKDAY = 3          # Monday=0 … Thursday=3
_RESET_HOUR_UTC = 7


# ──────────────────────────────────────────────────────────────────────────────
# Cycle helpers
# ──────────────────────────────────────────────────────────────────────────────


def current_cycle_start(now: Optional[datetime] = None) -> datetime:
    """Return the datetime of the most recent Thursday 07:00 UTC cycle start.

    If today is Thursday but before 07:00 UTC, returns last week's Thursday.
    """
    utc_now = now or datetime.now(timezone.utc)
    if utc_now.tzinfo is not None:
        utc_now = utc_now.replace(tzinfo=None)

    days_since = (utc_now.weekday() - _RESET_WEEKDAY) % 7
    cycle = utc_now.replace(
        hour=_RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_since)

    if cycle > utc_now:
        cycle -= timedelta(days=7)

    return cycle


def _lower_threshold(power_state: Optional[str]) -> int:
    """Absolute lower merit threshold (downgrade boundary) for a state."""
    return {
        "Exploited":  MERIT_ACQUIRE,
        "Fortified":  MERIT_FORTIFIED,
        "Stronghold": MERIT_STRONGHOLD,
    }.get(power_state or "", MERIT_ACQUIRE)


def _band_width(power_state: Optional[str]) -> float:
    """Merit band width for a given power state."""
    return {
        "Exploited":  float(BAND_EXPLOITED),
        "Fortified":  float(BAND_FORTIFIED),
        "Stronghold": float(BAND_STRONGHOLD),
    }.get(power_state or "", float(BAND_EXPLOITED))


# ──────────────────────────────────────────────────────────────────────────────
# Decay rate calculation
# ──────────────────────────────────────────────────────────────────────────────


def _decay_rate(power_state: Optional[str], progress: float) -> float:
    """Compute the merit decay rate (0.0–1.0) for a system.

    Returns a fraction (e.g. 0.026 = 2.6%) based on linear interpolation
    between the min and max endpoints for the given power state.

    Returns 0.0 for states that don't decay (Acquisition/Unoccupied/Contested)
    or when progress is below 25%.
    """
    if progress < 0.251:
        return 0.0

    endpoints = {
        "Stronghold": _DECAY_STRONGHOLD,
        "Fortified":  _DECAY_FORTIFIED,
        "Exploited":  _DECAY_EXPLOITED,
    }.get(power_state or "")

    if endpoints is None:
        return 0.0

    min_prog, min_rate, max_prog, max_rate = endpoints

    # Clamp progress to [min_prog, max_prog]
    p = max(min_prog, min(max_prog, progress))

    # Linear interpolation
    if max_prog == min_prog:
        return min_rate

    t = (p - min_prog) / (max_prog - min_prog)
    return min_rate + t * (max_rate - min_rate)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def compute_cp_decay(
    power_state: Optional[str],
    control_progress: Optional[float],
    undermining: Optional[int],
) -> int:
    """Compute the estimated CP merit decay for a system this cycle.

    Returns the decay in raw merits (integer), capped at the undermining
    value so effective_undermining never goes below 0.

    Parameters
    ----------
    power_state : str or None
        The PP state: "Stronghold", "Fortified", "Exploited", etc.
    control_progress : float or None
        Normalised progress 0.0–1.0+ within the current state band.
    undermining : int or None
        Total undermining merits delivered this cycle.
    """
    if power_state not in ("Stronghold", "Fortified", "Exploited"):
        return 0

    p = control_progress if control_progress is not None else 0.0
    u = undermining if undermining is not None else 0

    if u <= 0:
        return 0

    rate = _decay_rate(power_state, p)
    if rate <= 0.0:
        return 0

    # Compute absolute CP
    cp = _lower_threshold(power_state) + (p * _band_width(power_state))
    cp = max(0.0, cp)

    # Raw decay in merits
    raw_decay = cp * rate

    # Cap at undermining value (effective U floors at 0)
    return min(int(raw_decay), u)


def effective_undermining(
    undermining: Optional[int],
    cp_decay: Optional[int],
) -> int:
    """Compute effective undermining after applying CP decay.

    Returns max(0, undermining - cp_decay).
    """
    u = undermining or 0
    d = cp_decay or 0
    return max(0, u - d)