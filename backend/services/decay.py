"""Power Play control-point decay calculation.

At each cycle tick (Thursday 07:00 UTC) a system whose control progress is
above 25% of its tier decays.  The game books that decay as undermining for
the new cycle, so the journal's PowerplayStateUndermining already includes
it; subtracting it back out gives the "effective undermining" from real
opposing activity, and thus the true Net (R − U_eff).

Measured 2026-10-10 from ~5,100 live journal observations (FSDJump/Location
via EDDN + Spansh), as the floor of undermining against start-of-cycle
progress.  The fit is exact — every progress bin and percentile gives the
same constant:

    decay = k × band × max(0, p0 − 0.25)

    state        band (CP)   k        decay at 100%
    Exploited      350,000   1/12        21,875
    Fortified      650,000   0.170833    83,281
    Stronghold   1,000,000   5/24       156,250

p0 is the progress at the tick.  The journal's control_progress is live
(it moves with this cycle's R and U), so:

    p0 = control_progress − (reinforcement − undermining) / band

Decay never takes a system below 25% of its tier, so it can't downgrade a
system on its own.  Acquisition / Unoccupied systems don't decay.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tier bands (control points; must match scoring.py) and decay slopes
# ──────────────────────────────────────────────────────────────────────────────

BAND_EXPLOITED  = 350_000     # 0 → 350k
BAND_FORTIFIED  = 650_000     # 350k → 1M
BAND_STRONGHOLD = 1_000_000   # 1M → 2M

_BANDS = {
    "Exploited":  BAND_EXPLOITED,
    "Fortified":  BAND_FORTIFIED,
    "Stronghold": BAND_STRONGHOLD,
}

# Decay per unit of band above the 25% floor
_DECAY_SLOPE = {
    "Exploited":  1 / 12,     # 0.083333
    "Fortified":  0.170833,
    "Stronghold": 5 / 24,     # 0.208333
}

DECAY_FLOOR = 0.25

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


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def start_of_cycle_progress(
    power_state: Optional[str],
    control_progress: Optional[float],
    reinforcement: Optional[int],
    undermining: Optional[int],
) -> Optional[float]:
    """Back out this cycle's R/U from the live progress to get progress at the tick."""
    band = _BANDS.get(power_state or "")
    if band is None or control_progress is None:
        return None
    return control_progress - ((reinforcement or 0) - (undermining or 0)) / band


def compute_cp_decay(
    power_state: Optional[str],
    control_progress: Optional[float],
    reinforcement: Optional[int],
    undermining: Optional[int],
) -> int:
    """Compute the control-point decay booked as undermining this cycle.

    Returns an integer, capped at the undermining value so effective
    undermining never goes below 0.  Constant across a cycle for a given
    system, since it depends only on the progress at the tick.

    Parameters
    ----------
    power_state : str or None
        The PP state: "Stronghold", "Fortified", "Exploited", etc.
    control_progress : float or None
        Live progress 0.0–1.0+ within the current tier band.
    reinforcement, undermining : int or None
        Control points delivered this cycle (undermining includes decay).
    """
    slope = _DECAY_SLOPE.get(power_state or "")
    if slope is None:
        return 0

    u = undermining or 0
    if u <= 0:
        return 0

    p0 = start_of_cycle_progress(power_state, control_progress, reinforcement, undermining)
    if p0 is None or p0 <= DECAY_FLOOR:
        return 0

    # No clamp at 1.0: Strongholds above 100% fit the same line
    decay = slope * _BANDS[power_state] * (p0 - DECAY_FLOOR)
    return min(int(round(decay)), u)


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
