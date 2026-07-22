"""Standalone web server entrypoint.

Used when you want to run the API + UI without the GPIO daemon (e.g. on
a separate machine). The daemon is the normal way to start everything;
this exists so the API can be deployed independently.
"""

from __future__ import annotations

import logging
import signal
import threading

from ..api import create_app
from ..config import load_config
from ..core import AlertManager, InspectionEngine, StateStore
from ..hardware import CameraManager, create_gpio_backend
from ..paths import ensure_data_dirs, resolve_paths

log = logging.getLogger(__name__)


def run() -> None:
    cfg = load_config()
    paths = resolve_paths(cfg)
    ensure_data_dirs(paths)
    state = StateStore(paths.db_path)
    state.seed_pins_from_config(cfg.get("pins") or [])
    gpio = create_gpio_backend(cfg, persist_path=paths.mock_pins_path)
    gpio.setup(state.list_pins())
    cameras = CameraManager(cfg, paths)
    engine = InspectionEngine(
        default_method=str(cfg.get("inspection.match_method", "TM_CCOEFF_NORMED")),
        max_image_dimension=int(cfg.get("inspection.max_image_dimension", 1280)),
    )
    alerts = AlertManager(state)
    app, socketio, ctx = create_app(
        config=cfg, paths=paths, state=state, gpio=gpio,
        cameras=cameras, engine=engine, alerts=alerts,
    )
    # Wire the GPIO backend to action handlers in the same process
    from ..actions import set_gpio_backend
    set_gpio_backend(gpio)

    host = cfg.get("app.host", "0.0.0.0")
    port = int(cfg.get("app.port", 5000))
    log.info("web server: starting on %s:%d (env=%s, gpio=%s)",
             host, port, cfg.get("app.environment"), gpio.name)
    stop = threading.Event()
    def _on_signal(s, _f):  # type: ignore[no-untyped-def]
        log.info("web: signal %s", s)
        stop.set()
    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except (ValueError, OSError):
        pass
    try:
        socketio.run(app, host=host, port=port, debug=bool(cfg.get("app.debug", False)), allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            gpio.cleanup()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["run"]
