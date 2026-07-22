"""Triggers API — pin → job mapping."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ...models import Trigger
from ...models.pin import PinEdge

log = logging.getLogger(__name__)

bp = Blueprint("triggers", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_triggers():
    ctx = _ctx()
    return jsonify({"triggers": [t.to_dict() for t in ctx.state.list_triggers()]})


@bp.post("")
def upsert_trigger():
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    if "pin_id" not in data or "job_id" not in data:
        return jsonify({"error": "pin_id and job_id required"}), 400
    try:
        t = Trigger.from_dict(data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "bad_trigger", "message": str(e)}), 400
    ctx.state.upsert_trigger(t)
    return jsonify({"trigger": t.to_dict()}), 201


@bp.delete("/<trigger_id>")
def delete_trigger(trigger_id: str):
    ctx = _ctx()
    ctx.state.delete_trigger(trigger_id)
    return jsonify({"ok": True, "deleted": trigger_id})


@bp.post("/simulate/<trigger_id>")
def simulate_trigger(trigger_id: str):
    """Manually fire a trigger (useful for WSL testing)."""
    ctx = _ctx()
    t = ctx.state.get_trigger(trigger_id)
    if not t:
        return jsonify({"error": "not_found"}), 404
    # The daemon watches wait_for_edge — we can't fire that directly from
    # the web thread. Instead, we publish on the event bus and let the
    # daemon (if running) pick it up. As a synchronous fallback for tests,
    # we also call the alert_manager if no daemon is around.
    from ...core.event_bus import get_event_bus
    get_event_bus().publish("manual_trigger", {
        "trigger_id": t.id,
        "pin_id": t.pin_id,
        "job_id": t.job_id,
        "edge": t.edge.value,
    })
    return jsonify({"ok": True, "trigger": t.to_dict()})


__all__ = ["bp"]
