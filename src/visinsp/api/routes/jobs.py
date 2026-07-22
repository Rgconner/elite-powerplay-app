"""Jobs API — inspection job configuration."""

from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

from ...models import Job

log = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_jobs():
    ctx = _ctx()
    return jsonify({"jobs": [j.to_dict() for j in ctx.state.list_jobs()]})


@bp.get("/<job_id>")
def get_job(job_id: str):
    ctx = _ctx()
    j = ctx.state.get_job(job_id)
    if not j:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"job": j.to_dict()})


@bp.post("")
def create_job():
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    if "name" not in data or "reference_id" not in data or "camera_id" not in data:
        return jsonify({"error": "name, reference_id, camera_id required"}), 400
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data.setdefault("created_at", now)
    data["updated_at"] = now
    try:
        j = Job.from_dict(data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "bad_job", "message": str(e)}), 400
    # Pull defaults from settings if not provided
    settings = ctx.state.get_settings()
    if "threshold" not in data:
        j.threshold = settings.default_threshold
    if "threshold_step" not in data:
        j.threshold_step = settings.default_threshold_step
    ctx.state.upsert_job(j)
    return jsonify({"job": j.to_dict()}), 201


@bp.put("/<job_id>")
def update_job(job_id: str):
    ctx = _ctx()
    j = ctx.state.get_job(job_id)
    if not j:
        return jsonify({"error": "not_found"}), 404
    data = request.get_json(silent=True) or {}
    # Partial update
    for field in ("name", "reference_id", "camera_id", "notes"):
        if field in data:
            setattr(j, field, data[field])
    if "threshold" in data:
        j.threshold = float(data["threshold"])
    if "threshold_step" in data:
        j.threshold_step = float(data["threshold_step"])
    if "enabled" in data:
        j.enabled = bool(data["enabled"])
    if "actions_on_fail" in data:
        from ...models import actions_from_dicts
        j.actions_on_fail = actions_from_dicts(data["actions_on_fail"] or [])
    if "actions_on_pass" in data:
        from ...models import actions_from_dicts
        j.actions_on_pass = actions_from_dicts(data["actions_on_pass"] or [])
    j.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    ctx.state.upsert_job(j)
    return jsonify({"job": j.to_dict()})


@bp.delete("/<job_id>")
def delete_job(job_id: str):
    ctx = _ctx()
    ctx.state.delete_job(job_id)
    return jsonify({"ok": True, "deleted": job_id})


__all__ = ["bp"]
