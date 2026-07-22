"""References API — list / create / edit / delete reference images and their bounding boxes."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request

from ...models import BoundingBox, ReferenceImage

log = logging.getLogger(__name__)

bp = Blueprint("references", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


def _decode_image_b64(data_b64: str) -> np.ndarray:
    """Decode a base64 image payload into a BGR numpy array."""
    raw = base64.b64decode(data_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


@bp.get("")
def list_references():
    ctx = _ctx()
    refs = ctx.state.list_references()
    out = []
    for r in refs:
        d = r.to_dict()
        # Don't send bbox arrays for list view to keep payload small
        d["bbox_count"] = len(r.bboxes)
        d.pop("bboxes", None)
        d["image_url"] = f"/refs/{Path(r.image_path).name}" if r.image_path else None
        out.append(d)
    return jsonify({"references": out})


@bp.get("/<ref_id>")
def get_reference(ref_id: str):
    ctx = _ctx()
    r = ctx.state.get_reference(ref_id)
    if not r:
        return jsonify({"error": "not_found"}), 404
    d = r.to_dict()
    d["image_url"] = f"/refs/{Path(r.image_path).name}" if r.image_path else None
    return jsonify({"reference": d})


@bp.post("")
def create_reference():
    """Create a new reference.

    Body (JSON)::

        {
          "name": "Good part",
          "camera_id": "cam_0",
          "image_b64": "<base64 JPEG/PNG>",
          "bboxes": [ {"x":..,"y":..,"w":..,"h":..,"label":"..","weight":1.0} ]
        }
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    if "name" not in data or "image_b64" not in data:
        return jsonify({"error": "name and image_b64 required"}), 400
    try:
        img = _decode_image_b64(data["image_b64"])
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "bad_image", "message": str(e)}), 400
    h, w = img.shape[:2]
    ref_id = data.get("id") or f"ref_{uuid.uuid4().hex[:10]}"
    # Persist the image under references_dir
    fname = f"{ref_id}.png"
    img_path = ctx.paths.references_dir / fname
    img_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(img_path), img)
    bboxes = [BoundingBox.from_dict(b) for b in (data.get("bboxes") or [])]
    ref = ReferenceImage(
        id=ref_id,
        name=str(data.get("name", "Untitled")),
        camera_id=str(data.get("camera_id", "cam_0")),
        image_path=str(img_path),
        width=w,
        height=h,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        bboxes=bboxes,
        notes=str(data.get("notes", "")),
    )
    ctx.state.upsert_reference(ref)
    # Drop cached reference in the engine so the next inspect reloads.
    ctx.engine.invalidate(ref_id)
    log.info("reference created: %s (%s, %dx%d)", ref.id, ref.name, w, h)
    return jsonify({"reference": ref.to_dict()}), 201


@bp.post("/capture")
def capture_reference():
    """Capture a frame from a camera and store it as a (box-less) reference.

    The operator can then draw bounding boxes in the UI.
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    camera_id = data.get("camera_id", "cam_0")
    name = data.get("name") or f"Reference from {camera_id} @ {time.strftime('%Y-%m-%d %H:%M:%S')}"
    result = ctx.cameras.capture(camera_id, save=False)
    if result.get("frame") is None:
        return jsonify({"error": "capture_failed",
                        "message": result.get("error", "unknown")}), 500
    img = result["frame"]
    h, w = img.shape[:2]
    ref_id = f"ref_{uuid.uuid4().hex[:10]}"
    img_path = ctx.paths.references_dir / f"{ref_id}.png"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(img_path), img)
    ref = ReferenceImage(
        id=ref_id,
        name=name,
        camera_id=camera_id,
        image_path=str(img_path),
        width=w,
        height=h,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        bboxes=[],
    )
    ctx.state.upsert_reference(ref)
    ctx.engine.invalidate(ref_id)
    return jsonify({"reference": ref.to_dict()}), 201


@bp.put("/<ref_id>")
def update_reference(ref_id: str):
    """Update name / notes / bounding boxes. Image stays as-is."""
    ctx = _ctx()
    ref = ctx.state.get_reference(ref_id)
    if not ref:
        return jsonify({"error": "not_found"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data:
        ref.name = str(data["name"])
    if "notes" in data:
        ref.notes = str(data["notes"])
    if "bboxes" in data:
        ref.bboxes = [BoundingBox.from_dict(b) for b in (data["bboxes"] or [])]
    ctx.state.upsert_reference(ref)
    ctx.engine.invalidate(ref_id)
    return jsonify({"reference": ref.to_dict()})


@bp.delete("/<ref_id>")
def delete_reference(ref_id: str):
    ctx = _ctx()
    ctx.state.delete_reference(ref_id)
    ctx.engine.invalidate(ref_id)
    return jsonify({"ok": True, "deleted": ref_id})


__all__ = ["bp"]
