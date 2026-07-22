"""Inspections API - recent results + on-demand run."""

from __future__ import annotations

import logging
import time
import uuid

from flask import Blueprint, current_app, jsonify, request

from ...core.event_bus import get_event_bus
from ...models import SecondaryMetric

log = logging.getLogger(__name__)

bp = Blueprint("inspections", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_inspections():
    ctx = _ctx()
    job_id = request.args.get("job_id")
    limit = int(request.args.get("limit", 100))
    rows = ctx.state.list_inspections(job_id=job_id, limit=limit)
    return jsonify({"inspections": [r.to_dict() for r in rows]})


@bp.post("/run")
def run_inspection_now():
    """Manually trigger an inspection for a job.

    Captures a frame, runs the engine, records the result, raises an
    alert if it failed, and returns the inspection dict.
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    job = ctx.state.get_job(job_id)
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    ref = ctx.state.get_reference(job.reference_id)
    if not ref:
        return jsonify({"error": "reference_not_found"}), 404
    if not ref.bboxes:
        return jsonify({"error": "reference_has_no_bboxes"}), 400

    cap = ctx.cameras.capture(job.camera_id, save=True)
    if cap.get("frame") is None:
        return jsonify({"error": "capture_failed",
                        "message": cap.get("error", "unknown")}), 500
    method = data.get("method") or ctx.config.get("inspection.match_method", "TM_CCOEFF_NORMED")
    secondary = SecondaryMetric.from_str(
        data.get("secondary") or ctx.config.get("inspection.secondary_metric", "none")
    )
    try:
        result = ctx.engine.inspect(
            cap["frame"],
            ref,
            job,
            method=method,
            secondary=secondary,
            image_path=str(cap["path"]) if cap.get("path") else None,
        )
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": "inspect_failed", "message": str(e)}), 400
    ctx.state.record_inspection(result)
    get_event_bus().publish("inspection_complete", result.to_dict())
    if not result.passed:
        ctx.alerts.raise_alert(result, job)
    else:
        ctx.alerts.record_pass(result, job)
    return jsonify({"inspection": result.to_dict()}), 201


@bp.get("/threshold-history")
def threshold_history():
    ctx = _ctx()
    job_id = request.args.get("job_id")
    limit = int(request.args.get("limit", 100))
    rows = ctx.state.list_threshold_history(job_id=job_id, limit=limit)
    return jsonify({"history": rows})


__all__ = ["bp"]
