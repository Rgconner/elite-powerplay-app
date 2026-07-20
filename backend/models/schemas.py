"""Pydantic v2 response schemas for the Elite Powerplay API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

_from_orm = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# IngestionRun
# ---------------------------------------------------------------------------


class IngestionRunSchema(BaseModel):
    model_config = _from_orm

    id: int
    source: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    records_processed: int


# ---------------------------------------------------------------------------
# AdminSetting
# ---------------------------------------------------------------------------


class AdminSettingSchema(BaseModel):
    model_config = _from_orm

    id: int
    key: str
    value: str


# ---------------------------------------------------------------------------
# Power Play system entry (latest snapshot joined)
# ---------------------------------------------------------------------------


class PPSystemEntry(BaseModel):
    """A system under a Power's influence, enriched with its latest PP snapshot."""

    system_id64: int
    name: str
    x: float
    y: float
    z: float
    allegiance: Optional[str] = None
    population: Optional[int] = None

    # Latest snapshot fields
    power: Optional[str] = None
    power_state: Optional[str] = None
    reinforcement: Optional[int] = None
    undermining: Optional[int] = None
    control_progress: Optional[float] = None
    snapshot_time: Optional[datetime] = None

    # When Spansh last received game data for this system (authoritative data age)
    spansh_updated_at: Optional[datetime] = None

    # Computed
    distance_from_center: Optional[float] = None
    # Derived ratio 0.0–1.0 (undermining / reinforcement); None if no data
    undermine_ratio: Optional[float] = None


# ---------------------------------------------------------------------------
# System history point
# ---------------------------------------------------------------------------


class SystemHistoryPoint(BaseModel):
    model_config = _from_orm

    snapshot_time: datetime
    power: Optional[str] = None
    power_state: Optional[str] = None
    reinforcement: Optional[int] = None
    undermining: Optional[int] = None
    control_progress: Optional[float] = None


# ---------------------------------------------------------------------------
# System search result
# ---------------------------------------------------------------------------


class SystemSearchResult(BaseModel):
    model_config = _from_orm

    system_id64: int
    name: str
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


# ---------------------------------------------------------------------------
# Powers list
# ---------------------------------------------------------------------------


class PowersList(BaseModel):
    powers: list[str]


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------


class RecommendationItem(BaseModel):
    system_id64: int
    system_name: str
    score: float
    type: str                           # "fortify" | "expand"
    reasons: list[str]
    power_state: Optional[str] = None
    reinforcement: Optional[int] = None
    undermining: Optional[int] = None
    undermine_ratio: Optional[float] = None
    # Normalized progress toward next state transition (0.0–1.0+)
    # < 0 = already past downgrade threshold (critical)
    # >= 1.0 = past upgrade threshold (no action needed / suppress)
    control_progress: Optional[float] = None
    # Estimated days until state degrades; 0.0 = failing now; None = not at risk
    # Formula: progress × 7  (progress IS the normalized time-remaining fraction)
    days_to_failure: Optional[float] = None
    distance_from_center: Optional[float] = None
    # "worsening" | "improving" | "stable" | "unknown"
    threat_trend: str = "unknown"
    # ── Absolute merit context (from confirmed thresholds 120k/333k/667k) ──
    # Absolute merit position on the 0→667k scale
    merit_position: Optional[int] = None
    # Merits above downgrade threshold — how much cushion remains
    buffer_merits: Optional[int] = None
    # Additional merits needed to reach 50% progress (safe zone)
    merits_to_safety: Optional[int] = None
    # Additional merits needed to reach 100% (next state upgrade)
    merits_to_upgrade: Optional[int] = None
    # For expand items: "fortified" | "stronghold" | "both" | "expansion" — which anchor qualifies it
    anchor_type: Optional[str] = None
    # For expand items: JSON string [{power, progress}, ...] from power_conflict_progress.
    # Mirrors the same field on ContestedSystemInfo — enables per-power progress bars in the UI.
    conflict_progress: Optional[str] = None


class RecommendationsResponse(BaseModel):
    fortify: list[RecommendationItem]
    expand: list[RecommendationItem]
    llm_summary: Optional[str] = None


# ---------------------------------------------------------------------------
# Target Analysis
# ---------------------------------------------------------------------------


class TargetAnalysisItem(BaseModel):
    """One enemy system scored for undermining priority."""

    system_id64: int
    system_name: str
    controlling_power: str          # which target power controls this

    # PP state
    power_state: Optional[str] = None
    control_progress: Optional[float] = None
    reinforcement: Optional[int] = None
    undermining: Optional[int] = None

    # Vulnerability score (0–1000+). Higher = better undermining target.
    # Accounts for: current progress (close to 0 = losing state soon),
    # state value (Stronghold > Fortified > Exploited), proximity to attacker.
    score: float
    reasons: list[str]

    # Distance from the attacker's nearest controlled system (LY)
    distance_from_attacker: Optional[float] = None

    # Estimated days until the system drops one state at current undermine rate
    days_to_downgrade: Optional[float] = None

    # Trend across snapshots
    trend: str = "unknown"          # worsening | improving | stable | unknown

    # True when this is a Contested system (our power has merits here but hasn't
    # fully flipped it yet — or enemy is contesting one of ours)
    contested: bool = False


class TargetAnalysisRequest(BaseModel):
    attacker_power: str             # e.g. "Aisling Duval"
    target_powers: list[str]        # one or more powers to analyse


class TargetAnalysisResponse(BaseModel):
    targets: list[TargetAnalysisItem]
    attacker_power: str
    target_powers: list[str]
    # Active scoring thresholds sent back so the UI can render calibrated labels
    # without needing a separate /admin/settings round-trip
    progress_thresholds: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Contested Systems
# ---------------------------------------------------------------------------


class ContestedSystemInfo(BaseModel):
    """A system currently in Contested state (Unoccupied with 2+ powers fighting).
    No scoring — listed purely for awareness."""

    system_id64: int
    system_name: str
    controlling_power: str          # "Multiple" or first power listed
    power_state: str = "Contested"
    control_progress: Optional[float] = None
    reinforcement: Optional[int] = None
    undermining: Optional[int] = None
    distance_from_power: Optional[float] = None   # distance from nearest system of selected power
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    # Comma-separated list of all contesting powers e.g. "A. Lavigny-Duval,Aisling Duval"
    powers_list: Optional[str] = None
    # JSON string: [{power: str, progress: float}, ...]
    conflict_progress: Optional[str] = None
    # When Spansh last received game data for this system
    spansh_updated_at: Optional[datetime] = None
