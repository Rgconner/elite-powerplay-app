"""Classifies WHY a fortify-risk system is at risk: active attack vs. neglect.

This is the PowerPlay-domain version of the decay-vs-attack disambiguation
problem: a system's buffer eroding tells a player it needs attention, but not
what kind. Reinforcing works either way, but the two cases mean different
things to a player deciding where to spend merits:
  - ATTACK  : a rival is actively undermining faster than anyone is
              reinforcing — the fight continues after you leave; a one-time
              top-up won't hold unless the undermining stops too.
  - NEGLECT : nobody is undermining, the buffer just eroded from nobody
              reinforcing it — a one-time push rebuilds the cushion and the
              system is fine again with no ongoing fight.

Reuses NEGLECT_THRESHOLD = 0.25, matching the existing
`target_progress_high` convention already used elsewhere in scoring.py's
DEFAULTS for "HIGH vulnerability" — not a new number invented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

NEGLECT_THRESHOLD = 0.25


class FortifyCause(str, Enum):
    ATTACK = "attack"
    NEGLECT = "neglect"
    NONE = "none"


@dataclass
class FortifyRisk:
    cause: FortifyCause
    reasons: list[str]


def classify_fortify_cause(
    control_progress: Optional[float],
    reinforcement: Optional[int],
    undermining: Optional[int],
    neglect_threshold: float = NEGLECT_THRESHOLD,
) -> FortifyRisk:
    r = reinforcement or 0
    u = undermining or 0
    p = control_progress if control_progress is not None else 0.5

    if u > r:
        return FortifyRisk(
            FortifyCause.ATTACK,
            [f"Undermining ({u:,}) exceeds reinforcement ({r:,}) this cycle — actively being pushed down"],
        )
    if p <= neglect_threshold:
        return FortifyRisk(
            FortifyCause.NEGLECT,
            [f"Buffer at {p:.1%} with no active undermining — needs reinforcement to rebuild, not defense"],
        )
    return FortifyRisk(FortifyCause.NONE, [])
