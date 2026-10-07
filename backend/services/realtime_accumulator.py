"""Realtime accumulator service — aggregates EDDN events into CP deltas.

Runs every 60 seconds via APScheduler. For each (power, system) pair with
recent EDDN events, computes the sum of merits received since the last
Spansh snapshot boundary, converts to CPs at 4:1 ratio, and determines
orientation (reinforcement vs undermining) based on controlling power.

UPSERTs results into pp_realtime_state table.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Merits to CP conversion ratio (4 merits = 1 CP)
MERITS_TO_CP_RATIO = 4.0


def get_latest_spansh_boundary(system_id64: int, db: Session) -> Optional[datetime]:
    """Get the latest spansh_updated_at for a system from pp_system_snapshots.
    
    Returns None if no snapshot exists for this system.
    """
    result = db.execute(
        text("""
            SELECT MAX(spansh_updated_at) as latest_ts
            FROM pp_system_snapshots
            WHERE system_id64 = :system_id64
              AND spansh_updated_at IS NOT NULL
        """),
        {"system_id64": system_id64},
    ).fetchone()
    
    return result[0] if result and result[0] else None


def get_controlling_power(system_id64: int, db: Session) -> Optional[str]:
    """Get the controlling power for a system from the latest snapshot.
    
    Returns None if no snapshot exists or if the system is uncontrolled.
    """
    result = db.execute(
        text("""
            SELECT power
            FROM pp_system_snapshots
            WHERE system_id64 = :system_id64
            ORDER BY snapshot_time DESC
            LIMIT 1
        """),
        {"system_id64": system_id64},
    ).fetchone()
    
    return result[0] if result else None


def aggregate_events_for_power_system(
    power: str,
    system_id64: int,
    boundary_ts: datetime,
    db: Session,
) -> dict:
    """Aggregate EDDN events for a specific (power, system) pair since boundary.
    
    Returns dict with:
        - merits_since_ts: total merits since boundary
        - cp_since_ts: total CPs (merits / 4)
        - cp_as_reinforcement: CPs to add to reinforcement
        - cp_as_undermining: CPs to add to undermining
        - latest_event_ts: timestamp of most recent event
    """
    # Sum all merits from events after the boundary
    result = db.execute(
        text("""
            SELECT 
                COALESCE(SUM(merits), 0) as total_merits,
                MAX(event_timestamp) as latest_ts
            FROM pp_powerplay_events
            WHERE power = :power
              AND system_id64 = :system_id64
              AND event_timestamp > :boundary_ts
        """),
        {
            "power": power,
            "system_id64": system_id64,
            "boundary_ts": boundary_ts,
        },
    ).fetchone()
    
    total_merits = result[0] if result else 0
    latest_event_ts = result[1] if result else None
    
    # Convert merits to CPs
    cp_since_ts = total_merits / MERITS_TO_CP_RATIO
    
    # Determine orientation based on controlling power
    controlling_power = get_controlling_power(system_id64, db)
    
    # Orientation logic:
    # - If event_power == controlling_power → reinforcement
    # - If event_power != controlling_power → undermining
    # - If no controlling_power → reinforcement (all powers)
    if controlling_power is None or power == controlling_power:
        cp_as_reinforcement = cp_since_ts
        cp_as_undermining = 0.0
    else:
        cp_as_reinforcement = 0.0
        cp_as_undermining = cp_since_ts
    
    return {
        "merits_since_ts": total_merits,
        "cp_since_ts": cp_since_ts,
        "cp_as_reinforcement": cp_as_reinforcement,
        "cp_as_undermining": cp_as_undermining,
        "latest_event_ts": latest_event_ts,
    }


def upsert_realtime_state(
    power: str,
    system_id64: int,
    controlling_power: Optional[str],
    boundary_ts: datetime,
    aggregation: dict,
    db: Session,
) -> None:
    """UPSERT aggregated realtime state into pp_realtime_state table."""
    db.execute(
        text("""
            INSERT INTO pp_realtime_state (
                power, system_id64, controlling_power, boundary_ts,
                merits_since_ts, cp_since_ts, cp_as_reinforcement,
                cp_as_undermining, latest_event_ts, refreshed_at
            ) VALUES (
                :power, :system_id64, :controlling_power, :boundary_ts,
                :merits_since_ts, :cp_since_ts, :cp_as_reinforcement,
                :cp_as_undermining, :latest_event_ts, NOW()
            )
            ON CONFLICT (power, system_id64) DO UPDATE SET
                controlling_power = EXCLUDED.controlling_power,
                boundary_ts = EXCLUDED.boundary_ts,
                merits_since_ts = EXCLUDED.merits_since_ts,
                cp_since_ts = EXCLUDED.cp_since_ts,
                cp_as_reinforcement = EXCLUDED.cp_as_reinforcement,
                cp_as_undermining = EXCLUDED.cp_as_undermining,
                latest_event_ts = EXCLUDED.latest_event_ts,
                refreshed_at = NOW()
        """),
        {
            "power": power,
            "system_id64": system_id64,
            "controlling_power": controlling_power,
            "boundary_ts": boundary_ts,
            "merits_since_ts": aggregation["merits_since_ts"],
            "cp_since_ts": aggregation["cp_as_reinforcement"] + aggregation["cp_as_undermining"],
            "cp_as_reinforcement": aggregation["cp_as_reinforcement"],
            "cp_as_undermining": aggregation["cp_as_undermining"],
            "latest_event_ts": aggregation["latest_event_ts"],
        },
    )


def run_realtime_accumulator(db: Session) -> int:
    """Main accumulator function — runs every 60 seconds.
    
    Returns the number of (power, system) pairs updated.
    """
    logger.info("Starting realtime accumulator run...")
    
    # Get all distinct (power, system_id64) pairs from recent events
    # We only process systems that have events in the last 7 days
    recent_pairs = db.execute(
        text("""
            SELECT DISTINCT power, system_id64
            FROM pp_powerplay_events
            WHERE event_timestamp > NOW() - INTERVAL '7 days'
              AND system_id64 IS NOT NULL
        """)
    ).fetchall()
    
    updated_count = 0
    
    for row in recent_pairs:
        power = row[0]
        system_id64 = row[1]
        
        # Get the Spansh boundary timestamp for this system
        boundary_ts = get_latest_spansh_boundary(system_id64, db)
        
        if boundary_ts is None:
            # No Spansh snapshot yet — skip this system
            logger.debug(
                "Skipping %s/%d: no Spansh snapshot",
                power, system_id64,
            )
            continue
        
        # Get controlling power for orientation
        controlling_power = get_controlling_power(system_id64, db)
        
        # Aggregate events since boundary
        aggregation = aggregate_events_for_power_system(
            power, system_id64, boundary_ts, db,
        )
        
        # Only upsert if there are merits to record
        if aggregation["merits_since_ts"] > 0:
            upsert_realtime_state(
                power, system_id64, controlling_power,
                boundary_ts, aggregation, db,
            )
            updated_count += 1
            logger.debug(
                "Updated %s/%d: %d merits (%.2f CP)",
                power, system_id64,
                aggregation["merits_since_ts"],
                aggregation["cp_since_ts"],
            )
    
    db.commit()
    logger.info("Realtime accumulator complete: %d pairs updated", updated_count)
    
    return updated_count