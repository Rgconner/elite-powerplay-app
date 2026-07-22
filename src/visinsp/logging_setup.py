"""
Logging setup for Visual Inspector.

Single entry point: :func:`configure_logging`. Idempotent — calling it
multiple times is safe; the root logger is only configured the first time.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from .config import Config


_CONFIGURED = False


def configure_logging(config: Config, paths=None) -> logging.Logger:
    """Configure the root logger from the supplied config.

    ``paths`` is an optional :class:`~visinsp.paths.Paths` instance; if
    given, a rotating file handler is added at ``paths.log_file``.
    """
    global _CONFIGURED
    root = logging.getLogger()

    level_name = (config.get("logging.level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)

    # Clear any existing handlers if we're reconfiguring (e.g. tests).
    if _CONFIGURED:
        for h in list(root.handlers):
            root.removeHandler(h)
    _CONFIGURED = True

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_to_console = bool(config.get("logging.log_to_console", True))
    if log_to_console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(formatter)
        ch.setLevel(level)
        root.addHandler(ch)

    log_to_file = bool(config.get("logging.log_to_file", True))
    if log_to_file and paths and paths.log_file:
        try:
            paths.log_file.parent.mkdir(parents=True, exist_ok=True)
            max_bytes = int(config.get("logging.max_bytes", 1_048_576))
            backup_count = int(config.get("logging.backup_count", 3))
            fh = logging.handlers.RotatingFileHandler(
                paths.log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            fh.setLevel(level)
            root.addHandler(fh)
        except OSError as e:
            # Don't fail startup just because we couldn't open the log file.
            sys.stderr.write(f"[logging_setup] could not open log file: {e}\n")

    # Quiet down very chatty libraries
    for noisy in ("PIL", "urllib3", "engineio", "socketio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root


__all__ = ["configure_logging"]
