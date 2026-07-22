"""Flask application factory.

The factory wires the routes, the SocketIO server, the static files
location, and a small :class:`AppContext` that handlers use to reach the
state store, GPIO backend, camera manager, inspection engine, and
alert manager.

The factory does not start any background threads — it just builds the
app. :mod:`visinsp.services.daemon` is responsible for the GPIO thread,
retention thread, etc.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from flask import Flask

from ..actions import set_socketio_emitter, set_visual_emitter
from ..config import Config, load_config
from ..core import AlertManager, InspectionEngine, RetentionWorker, StateStore
from ..core.event_bus import get_event_bus
from ..core.state_store import SCHEMA_VERSION
from ..hardware import CameraManager, create_gpio_backend
from ..paths import Paths, ensure_data_dirs, resolve_paths

log = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PACKAGE_ROOT / "web"


@dataclass
class AppContext:
    """Holds the long-lived services shared by all routes."""

    config: Config
    paths: Paths
    state: StateStore
    gpio: Any  # GpioBackend
    cameras: CameraManager
    engine: InspectionEngine
    alerts: AlertManager
    retention: Optional[RetentionWorker] = None

    def to_dict(self) -> dict:
        return {
            "config_path": str(self.config.path) if self.config.path else None,
            "schema_version": SCHEMA_VERSION,
            "environment": self.config.get("app.environment"),
            "theme": self.config.get("app.theme"),
            "gpio_backend": getattr(self.gpio, "name", "?"),
            "paths": self.paths.as_dict(),
        }


def _wire_action_emitters(socketio_instance) -> None:
    """Make the visual / notification action handlers use the live socketio."""
    def _emit(event: str, payload: Any) -> None:
        try:
            socketio_instance.emit(event, payload, namespace="/")
        except Exception:  # noqa: BLE001
            log.exception("socketio.emit failed for event=%s", event)
    set_visual_emitter(_emit)
    set_socketio_emitter(_emit)


def create_app(
    config: Optional[Config] = None,
    paths: Optional[Paths] = None,
    state: Optional[StateStore] = None,
    gpio: Any = None,
    cameras: Optional[CameraManager] = None,
    engine: Optional[InspectionEngine] = None,
    alerts: Optional[AlertManager] = None,
) -> tuple[Flask, Any, AppContext]:
    """Build a Flask app, the matching SocketIO server, and the shared context.

    The caller can pass any pre-built service, or ``None`` to have the
    factory build it from the active config.
    """
    from flask_socketio import SocketIO

    if config is None:
        config = load_config()
    if paths is None:
        paths = resolve_paths(config)
    ensure_data_dirs(paths)
    if state is None:
        state = StateStore(paths.db_path)
        state.seed_pins_from_config(config.get("pins") or [])
        # Initialise settings from config if missing
        s = state.get_settings()
        s.default_threshold = float(config.get("threshold.default", s.default_threshold))
        s.default_threshold_step = float(config.get("threshold.default_step", s.default_threshold_step))
        s.min_threshold = float(config.get("threshold.min", s.min_threshold))
        s.max_threshold = float(config.get("threshold.max", s.max_threshold))
        s.theme = str(config.get("app.theme", s.theme))
        s.retention_days = int(config.get("alerts.retention_days", s.retention_days))
        state.save_settings(s)
    if gpio is None:
        gpio = create_gpio_backend(config, persist_path=paths.mock_pins_path)
    if cameras is None:
        cameras = CameraManager(config, paths)
    if engine is None:
        method = str(config.get("inspection.match_method", "TM_CCOEFF_NORMED"))
        max_dim = int(config.get("inspection.max_image_dimension", 1280))
        engine = InspectionEngine(default_method=method, max_image_dimension=max_dim)
    if alerts is None:
        alerts = AlertManager(state)

    ctx = AppContext(
        config=config, paths=paths, state=state, gpio=gpio,
        cameras=cameras, engine=engine, alerts=alerts,
    )

    # ---- Flask app ----
    app = Flask(
        __name__,
        template_folder=str(WEB_DIR / "templates"),
        static_folder=str(WEB_DIR / "static"),
    )
    app.config["SECRET_KEY"] = str(config.get("app.secret_key") or "dev-secret")
    app.config["JSON_SORT_KEYS"] = False
    app.config["VISINSP_CTX"] = ctx

    # ---- SocketIO ----
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )
    _wire_action_emitters(socketio)
    ctx.to_dict()  # no-op, kept for clarity

    # Subscribe the alert manager to event-bus events for fan-out.
    bus = get_event_bus()
    bus.subscribe("alert_new", lambda _t, payload: socketio.emit("alert_new", payload, namespace="/"))
    bus.subscribe("alert_resolved", lambda _t, payload: socketio.emit("alert_resolved", payload, namespace="/"))
    bus.subscribe("threshold_changed", lambda _t, payload: socketio.emit("threshold_changed", payload, namespace="/"))
    bus.subscribe("inspection_complete", lambda _t, payload: socketio.emit("inspection_complete", payload, namespace="/"))
    bus.subscribe("pin_state", lambda _t, payload: socketio.emit("pin_state", payload, namespace="/"))

    # ---- register blueprints ----
    from .routes.alerts import bp as alerts_bp
    from .routes.cameras import bp as cameras_bp
    from .routes.inspections import bp as inspections_bp
    from .routes.jobs import bp as jobs_bp
    from .routes.pins import bp as pins_bp
    from .routes.references import bp as references_bp
    from .routes.settings import bp as settings_bp
    from .routes.triggers import bp as triggers_bp

    app.register_blueprint(pins_bp, url_prefix="/api/pins")
    app.register_blueprint(cameras_bp, url_prefix="/api/cameras")
    app.register_blueprint(references_bp, url_prefix="/api/references")
    app.register_blueprint(triggers_bp, url_prefix="/api/triggers")
    app.register_blueprint(jobs_bp, url_prefix="/api/jobs")
    app.register_blueprint(inspections_bp, url_prefix="/api/inspections")
    app.register_blueprint(alerts_bp, url_prefix="/api/alerts")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")

    # ---- HTML pages ----
    from .routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)

    # ---- error handlers ----
    @app.errorhandler(404)
    def _not_found(_e):  # type: ignore[no-untyped-def]
        from flask import jsonify, request
        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "path": request.path}), 404
        return ("Not found", 404)

    @app.errorhandler(400)
    def _bad_request(e):  # type: ignore[no-untyped-def]
        from flask import jsonify
        msg = getattr(e, "description", "bad request")
        return jsonify({"error": "bad_request", "message": msg}), 400

    @app.errorhandler(500)
    def _server_error(e):  # type: ignore[no-untyped-def]
        from flask import jsonify
        log.exception("server error: %s", e)
        return jsonify({"error": "server_error"}), 500

    # Make the app context reachable from any blueprint.
    @app.context_processor
    def inject_globals():  # type: ignore[no-untyped-def]
        return {
            "app_name": config.get("app.name", "Visual Inspector"),
            "app_version": config.get("app.version", "0.0.0"),
            "theme": config.get("app.theme", "g100"),
        }

    log.info("create_app: ready (env=%s, gpio=%s)",
             config.get("app.environment"),
             getattr(gpio, "name", "?"))
    return app, socketio, ctx


def create_socketio(app: Flask):
    """Re-create a SocketIO wrapper around an existing app (for tests)."""
    from flask_socketio import SocketIO
    return SocketIO(app, cors_allowed_origins="*", async_mode="threading")


__all__ = ["create_app", "create_socketio", "AppContext", "WEB_DIR"]
