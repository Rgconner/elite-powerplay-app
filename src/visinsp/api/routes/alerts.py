"""Alerts API - list, dismiss with verdict, get details."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ...models import AlertVerdict

log = logging.getLogger(__name__)

bp = Blueprint("alerts", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_alerts():
    ctx = _ctx()
    verdict = request.args.get("verdict")
    job_id = request.args.get("job_id")
    limit = int(request.args.get("limit", 100))
    v = AlertVerdict.from_str(verdict) if verdict else None
    rows = ctx.state.list_alerts(verdict=v, job_id=job_id, limit=limit)
    return jsonify({"alerts": [a.to_dict() for a in rows]})


@bp.get("/<alert_id>")
def get_alert(alert_id: str):
    ctx = _ctx()
    a = ctx.state.get_alert(alert_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"alert": a.to_dict()})


@bp.post("/<alert_id>/dismiss")
def dismiss_alert(alert_id: str):
    """Dismiss an alert with a verdict (valid | false_positive | false_negative).

    The verdict drives the threshold auto-adjust:
      * valid           -> no change
      * false_positive  -> raise threshold by job.threshold_step
      * false_negative  -> lower threshold by job.threshold_step
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    verdict = AlertVerdict.from_str(data.get("verdict"))
    if verdict == AlertVerdict.PENDING:
        return jsonify({"error": "bad_verdict",
                        "message": "verdict must be one of valid, false_positive, false_negative"}), 400
    notes = str(data.get("notes", ""))
    actor = str(data.get("actor", "operator"))
    result = ctx.alerts.dismiss_alert(alert_id, verdict, notes=notes, actor=actor)
    if result is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(result)


__all__ = ["bp"]
