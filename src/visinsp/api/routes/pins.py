"""Pins API + mock-control endpoints."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ...models import Pin, PinEdge
from ...models.pin import PinDirection

log = logging.getLogger(__name__)

bp = Blueprint("pins", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.get("")
def list_pins():
    """Return every configured pin and its current state."""
    ctx = _ctx()
    states = {s.id: s for s in ctx.gpio.get_states()}
    out = []
    for pin in ctx.state.list_pins():
        st = states.get(pin.id)
        out.append({
            **pin.to_dict(),
            "level": st.level if st else 0,
            "last_edge": st.last_edge if st else None,
            "last_edge_kind": st.last_edge_kind if st else None,
        })
    return jsonify({"pins": out, "backend": getattr(ctx.gpio, "name", "?")})


@bp.post("")
def upsert_pin():
    """Create or update a pin."""
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    if "id" not in data and "bcm" not in data:
        return jsonify({"error": "id and bcm required"}), 400
    try:
        pin = Pin.from_dict(data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "bad_pin", "message": str(e)}), 400
    ctx.state.upsert_pin(pin)
    # Re-init the GPIO backend's pin set
    ctx.gpio.setup([pin])
    log.info("pin upserted: %s (bcm %s)", pin.id, pin.bcm)
    return jsonify({"pin": pin.to_dict()})


@bp.delete("/<pin_id>")
def delete_pin(pin_id: str):
    ctx = _ctx()
    ctx.state.delete_pin(pin_id)
    return jsonify({"ok": True, "deleted": pin_id})


@bp.get("/<pin_id>")
def get_pin(pin_id: str):
    ctx = _ctx()
    pin = ctx.state.get_pin(pin_id)
    if not pin:
        return jsonify({"error": "not_found"}), 404
    st = next((s for s in ctx.gpio.get_states() if s.id == pin_id), None)
    return jsonify({
        "pin": pin.to_dict(),
        "level": st.level if st else 0,
        "last_edge": st.last_edge if st else None,
    })


# ---- mock-only controls (real backends will 404) ----

@bp.post("/<pin_id>/toggle")
def toggle_pin(pin_id: str):
    """WSL / mock only: flip the pin level and fire an edge."""
    ctx = _ctx()
    if not hasattr(ctx.gpio, "toggle"):
        return jsonify({"error": "backend_does_not_support_toggle",
                        "backend": ctx.gpio.name}), 400
    try:
        new_level = ctx.gpio.toggle(pin_id)
    except KeyError:
        return jsonify({"error": "unknown_pin"}), 404
    return jsonify({"ok": True, "pin_id": pin_id, "level": new_level})


@bp.post("/<pin_id>/simulate")
def simulate_pin(pin_id: str):
    """WSL / mock only: set the level and fire an edge."""
    ctx = _ctx()
    if not hasattr(ctx.gpio, "simulate_edge"):
        return jsonify({"error": "backend_does_not_support_simulate",
                        "backend": ctx.gpio.name}), 400
    payload = request.get_json(silent=True) or {}
    level = int(payload.get("level", 0))
    ctx.gpio.simulate_edge(pin_id, level)
    return jsonify({"ok": True, "pin_id": pin_id, "level": level})


@bp.post("/<pin_id>/set")
def set_pin(pin_id: str):
    """Drive an output pin to a specific level (no edge event)."""
    ctx = _ctx()
    payload = request.get_json(silent=True) or {}
    level = int(payload.get("level", 0))
    try:
        ctx.gpio.write(pin_id, level)
    except (ValueError, KeyError) as e:
        return jsonify({"error": "write_failed", "message": str(e)}), 400
    return jsonify({"ok": True, "pin_id": pin_id, "level": level})


__all__ = ["bp"]
