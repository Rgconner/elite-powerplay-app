"""Telemetry router — aggregated feed health for all data sources.

Returns a single JSON document with green/yellow/red status for each feed:
  - Spansh batch ingest  (source="spansh_pp" in ingestion_runs)
  - EDSM sync            (source="edsm"      in ingestion_runs)
  - EDDN real-time stream (singleton row in eddn_feed_stats)
  - Spansh enrichment    (today's row in enrichment_stats + cache size)

JWT-gated via AdminUserDep — same auth as all other admin endpoints.
"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.session import get_db
from routers.deps import AdminUserDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# ── Freshness thresholds ───────────────────────────────────────────────────────

# Spansh ingest runs every N hours (default 24). Yellow if >2× overdue, red if >3×.
_SPANSH_INTERVAL_H: int = int(os.getenv("SPANSH_INGEST_INTERVAL_HOURS", "24"))
_SPANSH_YELLOW_H: float = _SPANSH_INTERVAL_H * 2
_SPANSH_RED_H: float    = _SPANSH_INTERVAL_H * 3

# EDSM sync runs every N hours (default 6).
_EDSM_INTERVAL_H: int = int(os.getenv("EDSM_SYNC_INTERVAL_HOURS", "6"))
_EDSM_YELLOW_H: float = _EDSM_INTERVAL_H * 2
_EDSM_RED_H: float    = _EDSM_INTERVAL_H * 3

# EDDN stream: green = event in last 30 min, yellow = 30 min–2 hr, red = 2+ hr
_EDDN_YELLOW_MIN: float = 30.0
_EDDN_RED_MIN: float    = 120.0


def _age_hours(ts: datetime | None) -> float | None:
    """Return how many hours ago *ts* occurred.  Returns None if ts is None."""
    if ts is None:
        return None
    now = datetime.utcnow()
    # Strip tz if aware so subtraction works uniformly
    ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
    return max((now - ts_naive).total_seconds() / 3600.0, 0.0)


def _ingest_status(last_run: dict | None, yellow_h: float, red_h: float) -> str:
    """Compute green/yellow/red for a batch ingest feed."""
    if last_run is None:
        return "red"
    if last_run.get("status") == "running":
        return "yellow"
    if last_run.get("status") == "failed":
        return "red"
    age = _age_hours(last_run.get("completed_at") or last_run.get("started_at"))
    if age is None:
        return "red"
    if age <= yellow_h:
        return "green"
    if age <= red_h:
        return "yellow"
    return "red"


def _eddn_status(last_event_ts: datetime | None, recorded_at: datetime | None) -> str:
    """Compute green/yellow/red for the EDDN real-time stream."""
    # If no stats row exists at all the listener has never written — red
    if recorded_at is None:
        return "red"
    # Check age of the most recent *event* first; fall back to recorded_at
    ts = last_event_ts or recorded_at
    age_min = (max((_age_hours(ts) or 0.0), 0.0)) * 60.0
    if age_min <= _EDDN_YELLOW_MIN:
        return "green"
    if age_min <= _EDDN_RED_MIN:
        return "yellow"
    return "red"


def _enrich_status(today_row: dict | None, total_cached: int) -> str:
    """Enrichment is healthy as long as the cache exists and has no all-error day."""
    if total_cached == 0:
        return "yellow"    # cache is empty but not necessarily broken
    if today_row and today_row.get("api_calls", 0) > 0:
        errors = today_row.get("api_errors", 0)
        calls  = today_row.get("api_calls", 0)
        if calls > 0 and errors / calls > 0.5:
            return "yellow"   # >50% error rate today
    return "green"


def _fmt(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.replace(tzinfo=None).isoformat() if ts else None


def _run_row(row) -> dict | None:
    if row is None:
        return None
    return {
        "id":               row.id,
        "status":           row.status,
        "started_at":       _fmt(row.started_at),
        "completed_at":     _fmt(row.completed_at),
        "records_processed": row.records_processed,
        "duration_seconds": row.duration_seconds,
        "api_calls_made":   row.api_calls_made,
        "api_errors":       row.api_errors,
        "error_count":      row.error_count,
        "error_detail":     row.error_detail,
        "bytes_downloaded": getattr(row, "bytes_downloaded", 0) or 0,
        "pages_fetched":    getattr(row, "pages_fetched", 0) or 0,
    }


@router.get("")
def get_telemetry(
    request: Request,
    admin: AdminUserDep,
    db: Session = Depends(get_db),
) -> dict:
    """Return aggregated feed health for all four data sources.

    Requires admin JWT.  Returns green/yellow/red status per feed plus
    raw metrics for the dashboard to render.
    """
    # ── 1. Spansh ingest (last run) ───────────────────────────────────────────
    from models.models import IngestionRun
    spansh_run = (
        db.query(IngestionRun)
        .filter(IngestionRun.source == "spansh_pp")
        .order_by(IngestionRun.started_at.desc())
        .first()
    )
    spansh_last = _run_row(spansh_run)

    # Last 5 runs for history panel
    spansh_history = [
        _run_row(r)
        for r in db.query(IngestionRun)
        .filter(IngestionRun.source == "spansh_pp")
        .order_by(IngestionRun.started_at.desc())
        .limit(5)
        .all()
    ]

    # Next scheduled run (from APScheduler)
    spansh_next: str | None = None
    try:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler:
            job = scheduler.get_job("spansh_ingest")
            if job and job.next_run_time:
                spansh_next = job.next_run_time.isoformat()
    except Exception:
        pass

    # ── 2. EDSM sync (last run) ───────────────────────────────────────────────
    edsm_run = (
        db.query(IngestionRun)
        .filter(IngestionRun.source == "edsm")
        .order_by(IngestionRun.started_at.desc())
        .first()
    )
    edsm_last = _run_row(edsm_run)

    edsm_history = [
        _run_row(r)
        for r in db.query(IngestionRun)
        .filter(IngestionRun.source == "edsm")
        .order_by(IngestionRun.started_at.desc())
        .limit(5)
        .all()
    ]

    edsm_next: str | None = None
    try:
        if scheduler:
            job = scheduler.get_job("edsm_sync")
            if job and job.next_run_time:
                edsm_next = job.next_run_time.isoformat()
    except Exception:
        pass

    # ── 3. EDDN feed stats (singleton) ───────────────────────────────────────
    eddn_row = db.execute(
        text("SELECT * FROM eddn_feed_stats WHERE id = 1")
    ).mappings().first()

    eddn_data: dict = {}
    if eddn_row:
        import json as _json
        top_schemas: dict = {}
        try:
            raw_schemas = eddn_row.get("top_schemas")
            if raw_schemas:
                top_schemas = _json.loads(raw_schemas)
        except Exception:
            pass

        eddn_data = {
            "recorded_at":              _fmt(eddn_row["recorded_at"]),
            "listener_started_at":      _fmt(eddn_row["listener_started_at"]),
            "events_total":             eddn_row["events_total"],
            "events_last_5min":         eddn_row["events_last_5min"],
            "dedup_rejected":           eddn_row["dedup_rejected"],
            "decode_errors":            eddn_row["decode_errors"],
            "last_event_ts":            _fmt(eddn_row["last_event_ts"]),
            "messages_received_total":  eddn_row.get("messages_received_total", 0) or 0,
            "bytes_received_total":     eddn_row.get("bytes_received_total", 0) or 0,
            "skipped_schema_total":     eddn_row.get("skipped_schema_total", 0) or 0,
            "skipped_event_total":      eddn_row.get("skipped_event_total", 0) or 0,
            "messages_per_min":         eddn_row.get("messages_per_min"),
            "top_schemas":              top_schemas,
        }

    # ── 4. Enrichment stats (today) ───────────────────────────────────────────
    today_enrich = db.execute(
        text("""
            SELECT cache_hits, cache_misses, api_calls, api_errors, total_fetch_ms
            FROM enrichment_stats
            WHERE stat_date = DATE_TRUNC('day', NOW())
        """)
    ).mappings().first()

    total_cached_row = db.execute(
        text("SELECT COUNT(*) AS cnt FROM spansh_enrichment")
    ).fetchone()
    total_cached: int = total_cached_row[0] if total_cached_row else 0

    enrich_data: dict = {
        "total_cached": total_cached,
        "today": None,
    }
    if today_enrich:
        hits  = today_enrich["cache_hits"]
        total = hits + today_enrich["cache_misses"]
        hit_rate = round(hits / total * 100, 1) if total > 0 else None
        avg_ms   = (
            round(today_enrich["total_fetch_ms"] / today_enrich["api_calls"], 1)
            if today_enrich["api_calls"] > 0 else None
        )
        enrich_data["today"] = {
            "cache_hits":     hits,
            "cache_misses":   today_enrich["cache_misses"],
            "hit_rate_pct":   hit_rate,
            "api_calls":      today_enrich["api_calls"],
            "api_errors":     today_enrich["api_errors"],
            "avg_fetch_ms":   avg_ms,
            "bytes_fetched":  today_enrich.get("bytes_fetched", 0) or 0,
        }

    # ── Compute status colours ────────────────────────────────────────────────
    spansh_status = _ingest_status(spansh_last, _SPANSH_YELLOW_H, _SPANSH_RED_H)
    edsm_status   = _ingest_status(edsm_last,   _EDSM_YELLOW_H,   _EDSM_RED_H)
    eddn_status   = _eddn_status(
        eddn_row["last_event_ts"] if eddn_row else None,
        eddn_row["recorded_at"]   if eddn_row else None,
    )
    enrich_status = _enrich_status(
        enrich_data.get("today"), total_cached
    )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "feeds": {
            "spansh_ingest": {
                "status":    spansh_status,
                "last_run":  spansh_last,
                "history":   spansh_history,
                "next_run_at": spansh_next,
                "interval_hours": _SPANSH_INTERVAL_H,
            },
            "edsm_sync": {
                "status":    edsm_status,
                "last_run":  edsm_last,
                "history":   edsm_history,
                "next_run_at": edsm_next,
                "interval_hours": _EDSM_INTERVAL_H,
            },
            "eddn_stream": {
                "status": eddn_status,
                **eddn_data,
            },
            "enrichment": {
                "status": enrich_status,
                **enrich_data,
            },
        },
    }


@router.get("/history")
def get_telemetry_history(
    admin: AdminUserDep,
    db: Session = Depends(get_db),
    days: int = 7,
) -> dict:
    """Return per-day aggregates for the last N days (default 7).

    Includes:
      - ingestion_runs: daily count, avg duration, total records, total bytes per source
      - enrichment_stats: daily cache hit rate, API calls, bytes fetched
      - eddn: events_last_5min is a point-in-time snapshot, so we report the current
              events_total broken down by uptime instead of per-day.
    """
    from models.models import IngestionRun

    # ── Daily ingestion aggregate (last N days) ───────────────────────────────
    ingest_rows = db.execute(
        text("""
            SELECT
                DATE_TRUNC('day', started_at)   AS day,
                source,
                COUNT(*)                         AS run_count,
                SUM(records_processed)           AS total_records,
                SUM(bytes_downloaded)            AS total_bytes,
                SUM(pages_fetched)               AS total_pages,
                AVG(duration_seconds)            AS avg_duration_s,
                SUM(api_errors)                  AS total_api_errors
            FROM ingestion_runs
            WHERE started_at >= NOW() - INTERVAL ':days days'
              AND status IN ('completed', 'failed')
            GROUP BY DATE_TRUNC('day', started_at), source
            ORDER BY day DESC, source
        """).bindparams(days=days)
    ).mappings().all()

    ingest_by_day: dict = {}
    for r in ingest_rows:
        day_key = r["day"].date().isoformat() if r["day"] else "unknown"
        if day_key not in ingest_by_day:
            ingest_by_day[day_key] = {}
        ingest_by_day[day_key][r["source"]] = {
            "run_count":        r["run_count"],
            "total_records":    r["total_records"],
            "total_bytes":      r["total_bytes"] or 0,
            "total_pages":      r["total_pages"] or 0,
            "avg_duration_s":   round(float(r["avg_duration_s"]), 1) if r["avg_duration_s"] else None,
            "total_api_errors": r["total_api_errors"] or 0,
        }

    # ── Daily enrichment stats (last N days) ─────────────────────────────────
    enrich_rows = db.execute(
        text("""
            SELECT
                stat_date::date AS day,
                cache_hits, cache_misses,
                api_calls, api_errors,
                total_fetch_ms, bytes_fetched
            FROM enrichment_stats
            WHERE stat_date >= NOW() - (INTERVAL '1 day' * :days)
            ORDER BY stat_date DESC
        """),
        {"days": days},
    ).mappings().all()

    enrich_history = []
    for r in enrich_rows:
        total = (r["cache_hits"] or 0) + (r["cache_misses"] or 0)
        hit_rate = round(r["cache_hits"] / total * 100, 1) if total > 0 else None
        avg_ms   = (
            round(r["total_fetch_ms"] / r["api_calls"], 1)
            if r["api_calls"] and r["api_calls"] > 0 else None
        )
        enrich_history.append({
            "day":          r["day"].isoformat() if r["day"] else "unknown",
            "cache_hits":   r["cache_hits"] or 0,
            "cache_misses": r["cache_misses"] or 0,
            "hit_rate_pct": hit_rate,
            "api_calls":    r["api_calls"] or 0,
            "api_errors":   r["api_errors"] or 0,
            "avg_fetch_ms": avg_ms,
            "bytes_fetched": r["bytes_fetched"] or 0,
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "days": days,
        "ingest_by_day": ingest_by_day,
        "enrichment_history": enrich_history,
    }
