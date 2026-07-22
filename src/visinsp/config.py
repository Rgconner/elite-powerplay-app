"""
Configuration loader for Visual Inspector.

Reads the active config from the path given by the ``VISINSP_CONFIG`` env var
or, failing that, ``./config/config.json``. Falls back to a per-environment
preset (config/config.pi.json or config/config.wsl.json) and finally to
``config/config.example.json``.

This module re-exports the legacy ``Config`` class so existing call sites
keep working, and adds a small ``get_active_config_path`` helper.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def get_active_config_path() -> Path:
    """Return the path to the active JSON config, picking fallbacks as needed."""
    env_path = os.environ.get("VISINSP_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        # If VISINSP_CONFIG is set but doesn't exist, we still respect the
        # path so the user can see the FileNotFoundError they caused.
        return p

    candidate = PROJECT_ROOT / "config" / "config.json"
    if candidate.exists():
        return candidate

    env_name = os.environ.get("VISINSP_ENV", "auto").lower()
    if env_name == "auto":
        env_name = "wsl" if os.name != "posix" else "wsl"

    preset = CONFIG_DIR / f"config.{env_name}.json"
    if preset.exists():
        return preset

    example = CONFIG_DIR / "config.example.json"
    if example.exists():
        return example

    # Last resort — return the default location so the caller raises a clear
    # FileNotFoundError.
    return candidate


class Config:
    """JSON-backed configuration manager with dot-notation access.

    Backwards-compatible with the original VisInsp Config class. The
    ``load()`` method now resolves a default path automatically if none is
    given, so callers can simply do ``Config()`` to get the active config.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config: Dict[str, Any] = {}
        self._config_path: Optional[Path] = None
        if config_path:
            self.load(config_path)
        else:
            self.load(str(get_active_config_path()))

    # ---- loading / saving ----

    def load(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with open(path, "r", encoding="utf-8") as f:
            self._config = json.load(f)
        self._config_path = path

    def save(self, config_path: Optional[str] = None) -> None:
        path = Path(config_path) if config_path else self._config_path
        if not path:
            raise ValueError("No configuration path specified")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2)

    # ---- accessors ----

    def get(self, key: str, default: Any = None) -> Any:
        cur: Any = self._config
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        cur = self._config
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    def get_all(self) -> Dict[str, Any]:
        return self._config.copy()

    @property
    def path(self) -> Optional[Path]:
        return self._config_path

    # ---- dunder ----

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __repr__(self) -> str:
        return f"Config(path={self._config_path}, keys={list(self._config.keys())})"


def load_config(config_path: Optional[str] = None) -> Config:
    """Convenience wrapper used throughout the package."""
    return Config(config_path)


__all__ = ["Config", "load_config", "get_active_config_path", "PROJECT_ROOT", "CONFIG_DIR"]
