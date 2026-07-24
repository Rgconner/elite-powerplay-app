"""Architecture router — serves the system architecture graph for visualization.

Provides endpoints for the admin-only architecture visualization page.
The graph is defined in backend/architecture/schema.json and loaded at startup.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.session import get_db
from routers.deps import AdminUserDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/architecture", tags=["architecture"])

# Load architecture schema at module import time
SCHEMA_PATH = Path(__file__).parent.parent / "architecture" / "schema.json"

_architecture_schema: dict[str, Any] = {}
try:
    with open(SCHEMA_PATH, "r") as f:
        _architecture_schema = json.load(f)
    logger.info("Loaded architecture schema from %s", SCHEMA_PATH)
except Exception as e:
    logger.error("Failed to load architecture schema: %s", e)


@router.get("/schema")
def get_architecture_schema(
    _admin: dict = Depends(AdminUserDep),
) -> dict:
    """Return the full architecture graph JSON. Admin-only.
    
    The schema defines all services, tables, endpoints, and data flows
    in the system. Used by the frontend ArchitecturePage to render an
    interactive D3 force-directed graph.
    """
    return _architecture_schema


@router.get("/status")
def get_architecture_status(
    db: Session = Depends(get_db),
    _admin: dict = Depends(AdminUserDep),
) -> dict:
    """Return live status of each service and table. Admin-only.
    
    Queries the database for:
    - Last Spansh ingest run status
    - EDDN event count and latest event timestamp
    - Realtime state row count and latest refresh
    - Table row counts
    """
    status: dict[str, Any] = {
        "services": {},
        "tables": {},
    }
    
    # Spansh ingest status
    try:
        result = db.execute(
            text("""
                SELECT status, started_at, completed_at, records_processed
                FROM ingestion_runs
                WHERE source = 'spansh_pp'
                ORDER BY started_at DESC
                LIMIT 1
            """)
        ).fetchone()
        
        if result:
            status["services"]["spansh-ingest"] = {
                "status": result[0],
                "last_run": result[1].isoformat() if result[1] else None,
                "completed_at": result[2].isoformat() if result[2] else None,
                "records_processed": result[3],
            }
        else:
            status["services"]["spansh-ingest"] = {"status": "unknown"}
    except Exception as e:
        logger.warning("Failed to get spansh-ingest status: %s", e)
        status["services"]["spansh-ingest"] = {"status": "error", "error": str(e)}
    
    # EDDN events status
    try:
        result = db.execute(
            text("""
                SELECT COUNT(*) as event_count,
                       MAX(event_timestamp) as latest_event
                FROM pp_powerplay_events
            """)
        ).fetchone()
        
        status["services"]["eddn-listener"] = {
            "status": "running" if result and result[0] > 0 else "idle",
            "total_events": result[0] if result else 0,
            "latest_event": result[1].isoformat() if result and result[1] else None,
        }
    except Exception as e:
        logger.warning("Failed to get eddn-listener status: %s", e)
        status["services"]["eddn-listener"] = {"status": "error", "error": str(e)}
    
    # Realtime accumulator status
    try:
        result = db.execute(
            text("""
                SELECT COUNT(*) as row_count,
                       MAX(refreshed_at) as latest_refresh
                FROM pp_realtime_state
            """)
        ).fetchone()
        
        status["services"]["realtime-accumulator"] = {
            "status": "running" if result and result[0] > 0 else "idle",
            "active_pairs": result[0] if result else 0,
            "latest_refresh": result[1].isoformat() if result and result[1] else None,
        }
    except Exception as e:
        logger.warning("Failed to get realtime-accumulator status: %s", e)
        status["services"]["realtime-accumulator"] = {"status": "error", "error": str(e)}
    
    # Table row counts
    tables = [
        "pp_systems",
        "pp_system_snapshots",
        "pp_powerplay_events",
        "pp_realtime_state",
        "spansh_enrichment",
        "ingestion_runs",
        "admin_settings",
        "admin_users",
    ]
    
    for table in tables:
        try:
            result = db.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()
            status["tables"][table] = {"row_count": result or 0}
        except Exception as e:
            logger.warning("Failed to get row count for %s: %s", table, e)
            status["tables"][table] = {"row_count": 0, "error": str(e)}
    
    return status


@router.post("/validate")
def validate_architecture_schema(
    _admin: dict = Depends(AdminUserDep),
) -> dict:
    """Validate that all source_file paths in the schema exist. Admin-only.
    
    Checks that each node's source_file path points to an existing file.
    Returns a list of missing files.
    """
    missing_files: list[str] = []
    
    for node in _architecture_schema.get("nodes", []):
        source_file = node.get("source_file")
        if source_file:
            # Resolve relative to project root (parent of backend/)
            file_path = Path(__file__).parent.parent.parent / source_file
            if not file_path.exists():
                missing_files.append(source_file)
    
    return {
        "valid": len(missing_files) == 0,
        "missing_files": missing_files,
        "total_nodes": len(_architecture_schema.get("nodes", [])),
    }