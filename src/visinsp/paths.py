"""
Filesystem layout for Visual Inspector.

Centralises where every runtime artefact lives so the rest of the code
never has to think about relative paths.

All paths are resolved from the active :class:`~visinsp.config.Config`. By
default the daemon runs from the project root, so the resolved paths
will be something like::

    data/
    ├── references/    *.png reference images + .bbox.json sidecars
    ├── captures/      <timestamp>.jpg saved per trigger
    ├── alerts/        alert snapshots (currently unused, kept for future)
    ├── samples/       sample images used by WSL mock mode
    ├── mock_pins.json persisted mock-GPIO state
    └── visinsp.db     SQLite state store
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Config, PROJECT_ROOT

log = logging.getLogger(__name__)


@dataclass
class Paths:
    """Resolved, absolute filesystem paths used by the application."""

    data_dir: Path
    references_dir: Path
    captures_dir: Path
    alerts_dir: Path
    sample_images_dir: Path
    db_path: Path
    mock_pins_path: Path
    log_file: Optional[Path] = None
    upload_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        # upload_dir is where new reference images are stored before being
        # processed. It lives inside references_dir.
        self.upload_dir = self.references_dir / "_uploads"

    def as_dict(self) -> Dict[str, str]:
        return {
            "data_dir": str(self.data_dir),
            "references_dir": str(self.references_dir),
            "captures_dir": str(self.captures_dir),
            "alerts_dir": str(self.alerts_dir),
            "sample_images_dir": str(self.sample_images_dir),
            "db_path": str(self.db_path),
            "mock_pins_path": str(self.mock_pins_path),
            "log_file": str(self.log_file) if self.log_file else "",
            "upload_dir": str(self.upload_dir),
        }


def _resolve(value: str, base: Path) -> Path:
    """Resolve a config value (absolute or relative) against the project root."""
    p = Path(value)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def resolve_paths(config: Config) -> Paths:
    """Build a :class:`Paths` instance from a loaded config."""
    paths_cfg = config.get("paths", {}) or {}
    base = Path(os.environ.get("VISINSP_PROJECT_ROOT", str(PROJECT_ROOT)))

    log_file_raw = paths_cfg.get("log_file")
    log_file = _resolve(log_file_raw, base) if log_file_raw else None

    paths = Paths(
        data_dir=_resolve(paths_cfg.get("data_dir", "data"), base),
        references_dir=_resolve(paths_cfg.get("references_dir", "data/references"), base),
        captures_dir=_resolve(paths_cfg.get("captures_dir", "data/captures"), base),
        alerts_dir=_resolve(paths_cfg.get("alerts_dir", "data/alerts"), base),
        sample_images_dir=_resolve(paths_cfg.get("sample_images_dir", "data/samples"), base),
        db_path=_resolve(paths_cfg.get("db_path", "data/visinsp.db"), base),
        mock_pins_path=_resolve(paths_cfg.get("mock_pins_path", "data/mock_pins.json"), base),
        log_file=log_file,
    )
    return paths


def ensure_data_dirs(paths: Paths) -> None:
    """Create the on-disk data layout (idempotent)."""
    for d in (
        paths.data_dir,
        paths.references_dir,
        paths.captures_dir,
        paths.alerts_dir,
        paths.sample_images_dir,
        paths.upload_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Dict[str, Any], indent: int = 2) -> None:
    """Write a JSON file atomically-ish (write to .tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, default=str)
    tmp.replace(path)


def read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = ["Paths", "resolve_paths", "ensure_data_dirs", "write_json", "read_json"]
