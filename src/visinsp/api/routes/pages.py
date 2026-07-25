"""Flask blueprint for HTML pages.

Each page is a thin Jinja template that pulls in Carbon's CSS/JS from
the CDN and a small per-page JS module. Data is fetched from the JSON
API; the templates themselves only render shells.
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, render_template, send_from_directory

from ..app import WEB_DIR

log = logging.getLogger(__name__)

bp = Blueprint("pages", __name__)


def _ctx():
    return current_app.config["VISINSP_CTX"]


@bp.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        ctx=_ctx(),
        page="dashboard",
        title="Dashboard",
    )


@bp.route("/references")
def references_list():
    return render_template(
        "references.html",
        ctx=_ctx(),
        page="references",
        title="References",
    )


@bp.route("/references/<ref_id>/edit")
def reference_edit(ref_id: str):
    return render_template(
        "reference_edit.html",
        ctx=_ctx(),
        page="references",
        title="Edit Reference",
        ref_id=ref_id,
    )


@bp.route("/jobs")
def jobs_list():
    return render_template(
        "jobs.html",
        ctx=_ctx(),
        page="jobs",
        title="Jobs",
    )


@bp.route("/triggers")
def triggers_list():
    return render_template(
        "triggers.html",
        ctx=_ctx(),
        page="triggers",
        title="Triggers",
    )


@bp.route("/alerts")
def alerts_list():
    return render_template(
        "alerts.html",
        ctx=_ctx(),
        page="alerts",
        title="Alerts",
    )


@bp.route("/settings")
def settings_page():
    return render_template(
        "settings.html",
        ctx=_ctx(),
        page="settings",
        title="Settings",
    )


# ---- serve captures and reference images directly (outside /static) ----
@bp.route("/captures/<path:filename>")
def capture_file(filename: str):
    ctx = _ctx()
    return send_from_directory(str(ctx.paths.captures_dir), filename)


@bp.route("/refs/<path:filename>")
def reference_file(filename: str):
    ctx = _ctx()
    return send_from_directory(str(ctx.paths.references_dir), filename)


@bp.route("/healthz")
def healthz():
    return {"ok": True}


__all__ = ["bp"]