"""Cameras API."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

log = logging.getLogger(__name__)

bp = Blueprint("cameras", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_cameras():
    ctx = _ctx()
    return jsonify({"cameras": [c.to_dict() for c in ctx.cameras.list_cameras()]})


@bp.post("/refresh")
def refresh_cameras():
    ctx = _ctx()
    ctx.cameras.refresh()
    return jsonify({"cameras": [c.to_dict() for c in ctx.cameras.list_cameras()]})


@bp.post("/<camera_id>/capture")
def capture(camera_id: str):
    """Capture a frame from the named camera. Returns image metadata; the
    actual frame is *not* returned in the JSON to keep the response small.
    Use :func:`capture_image` to download the JPEG.
    """
    ctx = _ctx()
    save = request.args.get("save")
    if save is not None:
        save = save.lower() in ("1", "true", "yes")
    result = ctx.cameras.capture(camera_id, save=save)
    if result.get("frame") is None:
        return jsonify({"error": "capture_failed",
                        "message": result.get("error", "unknown")}), 500
    return jsonify({
        "camera_id": result.get("camera_id"),
        "width": result.get("width"),
        "height": result.get("height"),
        "image_url": f"/api/cameras/{camera_id}/image?path={result.get('path').name}" if result.get("path") else None,
        "saved_path": str(result.get("path")) if result.get("path") else None,
    })


@bp.get("/<camera_id>/image")
def capture_image(camera_id: str):
    """Download the most recent capture from the named camera."""
    ctx = _ctx()
    name = request.args.get("path", "")
    if not name:
        return jsonify({"error": "missing_path"}), 400
    # Basic safety: forbid ".."
    if ".." in name or "/" in name or "\\" in name:
        return jsonify({"error": "bad_path"}), 400
    p = Path(ctx.paths.captures_dir) / name
    if not p.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(str(p), mimetype="image/jpeg")


__all__ = ["bp"]
