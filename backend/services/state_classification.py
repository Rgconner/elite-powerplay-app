"""Single source of truth for PowerPlay 2.0 system-state classification.

Consolidates state-derivation logic that had drifted across scoring.py and
powers.py independently — most visibly the phantom `power_state = 'Acquisition'`
branch (copy-pasted into three query sites; never once written by ingestion.py)
and the missing Expansion category. inara.cz treats six states as distinct —
Unoccupied, Expansion, Contested, Exploited, Fortified, Stronghold — but this
app's raw Spansh vocabulary only has four (Exploited | Fortified | Stronghold |
Unoccupied), and ingestion.py's second pass collapses ALL multi-power Unoccupied
systems into one internal 'Contested' label without ever distinguishing a
single power's solo acquisition push. Every consumer should classify against
THIS module rather than re-deriving the distinction inline.

Owned states (Exploited/Fortified/Stronghold) are unambiguous — a single power
already controls the system, so they pass straight through. Unoccupied is
where the real distinction lives, based on how many powers have any recorded
presence:
    0 powers present  -> Unoccupied  (nobody has touched it)
    1 power present   -> Expansion   (solo acquisition push)
    2+ powers present -> Contested   (multi-power dispute over unclaimed territory)

NOTE: as of this module's introduction, ingestion.py never stores a row for
solo-power Unoccupied systems at all (see _iter_unoccupied_systems' `len(raw_p)
>= 2` filter) — so real EXPANSION classifications won't appear until that's
fixed separately. This module is correct for whatever data it's given; it does
not itself fix what data exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SystemState(str, Enum):
    UNOCCUPIED = "Unoccupied"
    EXPANSION = "Expansion"
    CONTESTED = "Contested"
    EXPLOITED = "Exploited"
    FORTIFIED = "Fortified"
    STRONGHOLD = "Stronghold"


_OWNED_STATES = {"Exploited", "Fortified", "Stronghold"}


@dataclass
class ClassifiedState:
    state: SystemState
    reasons: list[str]


def powers_present_count(powers_list: Optional[str]) -> int:
    """Count distinct powers with any recorded presence, from the
    comma-separated powers_list column (see ingestion._extract_powers_fields).

    NOTE: as observed in live data, a power can appear in powers_list with
    0.0 conflict_progress (listed but no merits earned yet) — this counts
    every listed power as "present" without a progress threshold, matching
    current ingestion behavior. If "present but hasn't actually contested
    yet" should NOT count toward Expansion/Contested, that's a real judgment
    call to make explicitly (see conflict_progress) rather than bake in here
    silently — flag it for review rather than guessing.
    """
    if not powers_list:
        return 0
    return len([p for p in powers_list.split(",") if p.strip()])


def classify_system(
    raw_power_state: Optional[str],
    powers_list: Optional[str],
) -> ClassifiedState:
    """Classify a system into one of the six PowerPlay 2.0 states.

    raw_power_state: the power_state column as stored (Exploited | Fortified |
        Stronghold | Unoccupied | Contested — 'Contested' is ingestion.py's own
        internal label, already pre-collapsed; see module docstring).
    powers_list: comma-separated powers_list column.
    """
    if raw_power_state in _OWNED_STATES:
        return ClassifiedState(
            SystemState(raw_power_state),
            [f"Owned state reported directly: {raw_power_state}"],
        )

    # 'Contested' rows were already pre-classified as multi-power by
    # ingestion's own pass (it only stores rows with 2+ powers under this
    # label) — trust that label directly rather than re-deriving from
    # powers_list, since ingestion never stores the raw 'Unoccupied' state
    # for these rows to re-derive from.
    if raw_power_state == "Contested":
        count = powers_present_count(powers_list)
        return ClassifiedState(
            SystemState.CONTESTED,
            [f"{count} powers present ({powers_list}) — multi-power dispute over unclaimed territory"],
        )

    # raw_power_state == 'Unoccupied' (or missing/unrecognized) — the only
    # case where powers_list actually needs to decide Expansion vs Unoccupied.
    count = powers_present_count(powers_list)
    if count == 0:
        return ClassifiedState(SystemState.UNOCCUPIED, ["No power has any recorded presence"])
    elif count == 1:
        return ClassifiedState(
            SystemState.EXPANSION,
            [f"Exactly one power ({powers_list}) pushing toward acquisition — solo expansion"],
        )
    else:
        return ClassifiedState(
            SystemState.CONTESTED,
            [f"{count} powers present ({powers_list}) — multi-power dispute over unclaimed territory"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# Expansion race signal — "is this snipable" for EXPANSION-state systems
# ──────────────────────────────────────────────────────────────────────────────
#
# Confirmed against inara.cz/elite/power-contested/4/: a rival's percentage
# is their share of the acquisition threshold and CAN exceed 100% — this is a
# horse race, not a 0-100% safe-zone position. "Snipable" means WE could win
# it: we're behind the current leader, but the gap is closeable. This is a
# tactical read only (the numbers) — whether a system is worth fighting for
# beyond the numbers (a "lost cause" vs. "needed for plan X" call) is a human
# judgment this module deliberately does not make; see conversation notes on
# the tactician/strategist distinction.

SNIPE_GAP_THRESHOLD = 0.5  # gap (as a fraction of the acquisition threshold)
                            # considered realistically closeable before cycle end


@dataclass
class ExpansionSignal:
    our_progress: float
    leading_rival: Optional[str]
    leading_rival_progress: float
    gap_to_lead: float   # our_progress - leading_rival_progress; negative = we're behind
    snipable: bool        # we're behind, but the gap is within snipe_gap_threshold


def compute_expansion_signal(
    our_power: str,
    conflict_progress_json: Optional[str],
    snipe_gap_threshold: float = SNIPE_GAP_THRESHOLD,
) -> Optional[ExpansionSignal]:
    """Compute our standing in an Expansion-state system's acquisition race.

    conflict_progress_json: the raw conflict_progress column — a JSON array
    of {"power": ..., "progress": ...} entries (see ingestion._extract_powers_fields).
    Returns None if there's no parseable race data at all.
    """
    if not conflict_progress_json:
        return None
    try:
        entries = json.loads(conflict_progress_json)
    except (TypeError, ValueError):
        return None
    if not entries:
        return None

    our_progress = 0.0
    rivals: list[tuple[str, float]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        power = entry.get("power")
        progress = entry.get("progress") or 0.0
        if power == our_power:
            our_progress = progress
        else:
            rivals.append((power, progress))

    if not rivals:
        return ExpansionSignal(our_progress, None, 0.0, our_progress, False)

    leading_rival, leading_progress = max(rivals, key=lambda item: item[1])
    gap = our_progress - leading_progress
    snipable = gap < 0 and abs(gap) <= snipe_gap_threshold

    return ExpansionSignal(
        our_progress=our_progress,
        leading_rival=leading_rival,
        leading_rival_progress=leading_progress,
        gap_to_lead=gap,
        snipable=snipable,
    )
