"""Command-line interface.

Subcommands:

    run      Start the daemon (GPIO + retention) and the web server.
    web      Start only the Flask + SocketIO web server (no GPIO thread).
    seed     Generate sample reference images + sample captures (WSL).
    init     Create the data directories and seed config + pins.
    info     Print config + environment summary as JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__
from ..config import get_active_config_path, load_config
from ..core import StateStore
from ..hardware import get_active_backend_name
from ..logging_setup import configure_logging
from ..paths import ensure_data_dirs, resolve_paths


def _setup_logging_from_config(config) -> None:
    paths = resolve_paths(config)
    configure_logging(config, paths)


def cmd_run(args: argparse.Namespace) -> int:
    """Start the full daemon (GPIO + web)."""
    config = load_config()
    _setup_logging_from_config(config)
    log = logging.getLogger("visinsp.cli")
    log.info("Visual Inspector %s starting (env=%s, config=%s)",
             __version__, config.get("app.environment"), get_active_config_path())

    # Start the daemon background work in a thread and the web server in
    # the main thread so signals are handled cleanly.
    from .daemon import Daemon
    from .web_server import run as run_web

    # If we have both to run, do it in one process: daemon thread + web main.
    # We do this by running the web server in the main thread; the daemon
    # threads are spawned by the Daemon object.
    from ..actions import set_gpio_backend
    from ..api import create_app
    from ..core import AlertManager, InspectionEngine
    from ..hardware import CameraManager, create_gpio_backend

    paths = resolve_paths(config)
    ensure_data_dirs(paths)
    state = StateStore(paths.db_path)
    state.seed_pins_from_config(config.get("pins") or [])
    gpio = create_gpio_backend(config, persist_path=paths.mock_pins_path)
    cameras = CameraManager(config, paths)
    engine = InspectionEngine(
        default_method=str(config.get("inspection.match_method", "TM_CCOEFF_NORMED")),
        max_image_dimension=int(config.get("inspection.max_image_dimension", 1280)),
    )
    alerts = AlertManager(state)
    set_gpio_backend(gpio)
    daemon = Daemon(
        config=config, paths=paths, state=state, gpio=gpio,
        cameras=cameras, engine=engine, alerts=alerts,
    )
    daemon.start()
    app, socketio, ctx = create_app(
        config=config, paths=paths, state=state, gpio=gpio,
        cameras=cameras, engine=engine, alerts=alerts,
    )
    # Inject the same daemon into the app context so the alert manager etc.
    # share state with the web handlers.
    app.config["VISINSP_CTX"].retention = daemon.retention

    host = config.get("app.host", "0.0.0.0")
    port = int(config.get("app.port", 5000))
    try:
        log.info("web: serving on http://%s:%d", host, port)
        socketio.run(app, host=host, port=port,
                     debug=bool(config.get("app.debug", False)),
                     allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from .web_server import run as run_web
    run_web()
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from ..paths import resolve_paths
    from .seed import seed
    config = load_config()
    paths = resolve_paths(config)
    seed(paths, count=args.count)
    print(f"Seeded {args.count} sample captures into {paths.sample_images_dir}")
    print(f"Reference images in {paths.references_dir}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    config = load_config()
    paths = resolve_paths(config)
    ensure_data_dirs(paths)
    state = StateStore(paths.db_path)
    state.seed_pins_from_config(config.get("pins") or [])
    print(f"data dir:     {paths.data_dir}")
    print(f"db:           {paths.db_path}")
    print(f"mock pins:    {paths.mock_pins_path}")
    print(f"samples:      {paths.sample_images_dir}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    config = load_config()
    paths = resolve_paths(config)
    info: Dict[str, Any] = {
        "version": __version__,
        "config_path": str(get_active_config_path()),
        "environment": config.get("app.environment"),
        "gpio_backend": get_active_backend_name(config),
        "theme": config.get("app.theme"),
        "paths": paths.as_dict(),
        "pin_count": len(config.get("pins") or []),
        "camera_count": len(config.get("cameras") or []),
    }
    print(json.dumps(info, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="visinsp",
        description="Visual Inspector — camera-based manufacturing defect detection.",
    )
    p.add_argument("--version", action="version", version=f"visinsp {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("run", help="Start the daemon and web server (default).")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("web", help="Start only the web server (no GPIO thread).")
    sp.set_defaults(func=cmd_web)

    sp = sub.add_parser("seed", help="Generate sample reference + capture images.")
    sp.add_argument("--count", type=int, default=5, help="How many sample captures to create.")
    sp.set_defaults(func=cmd_seed)

    sp = sub.add_parser("init", help="Create data dirs and seed pins (idempotent).")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("info", help="Print config + environment summary as JSON.")
    sp.set_defaults(func=cmd_info)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Default subcommand: run
        return cmd_run(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
