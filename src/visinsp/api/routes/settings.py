"""Settings API - read and update global app settings."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ...models import Settings

log = logging.getLogger(__name__)

bp = Blueprint("settings", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def get_settings():
    ctx = _ctx()
    return jsonify({"settings": ctx.state.get_settings().to_dict()})


@bp.put("")
def update_settings():
    ctx = _ctx()
    s: Settings = ctx.state.get_settings()
    data = request.get_json(silent=True) or {}
    if "default_threshold" in data:
        s.default_threshold = float(data["default_threshold"])
    if "default_threshold_step" in data:
        s.default_threshold_step = float(data["default_threshold_step"])
    if "min_threshold" in data:
        s.min_threshold = float(data["min_threshold"])
    if "max_threshold" in data:
        s.max_threshold = float(data["max_threshold"])
    if "retention_days" in data:
        s.retention_days = int(data["retention_days"])
    if "history_retention_days" in data:
        s.history_retention_days = int(data["history_retention_days"])
    if "theme" in data:
        s.theme = str(data["theme"])
        ctx.config.set("app.theme", s.theme)
    if "auto_dismiss_after_hours" in data:
        s.auto_dismiss_after_hours = int(data["auto_dismiss_after_hours"])
    ctx.state.save_settings(s)
    return jsonify({"settings": s.to_dict()})


@bp.get("/context")
def app_context():
    """Return the AppContext summary (used by the UI on first load)."""
    ctx = _ctx()
    return jsonify(ctx.to_dict())


__all__ = ["bp"]
