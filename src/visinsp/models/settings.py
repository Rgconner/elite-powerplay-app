"""Settings model — global, app-wide tunables."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Settings:
    """A small set of app-wide settings.

    Most configuration is still in the JSON config file; this dataclass
    only represents the subset that's mutable at runtime (theme, default
    threshold step, retention).
    """

    id: str = "singleton"
    default_threshold: float = 0.85
    default_threshold_step: float = 0.005
    min_threshold: float = 0.50
    max_threshold: float = 0.99
    retention_days: int = 30
    history_retention_days: int = 90
    theme: str = "g100"  # "g100" (dark) or "white" (light)
    auto_dismiss_after_hours: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "default_threshold": float(self.default_threshold),
            "default_threshold_step": float(self.default_threshold_step),
            "min_threshold": float(self.min_threshold),
            "max_threshold": float(self.max_threshold),
            "retention_days": int(self.retention_days),
            "history_retention_days": int(self.history_retention_days),
            "theme": self.theme,
            "auto_dismiss_after_hours": int(self.auto_dismiss_after_hours),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        return cls(
            id=str(data.get("id") or "singleton"),
            default_threshold=float(data.get("default_threshold", 0.85)),
            default_threshold_step=float(data.get("default_threshold_step", 0.005)),
            min_threshold=float(data.get("min_threshold", 0.50)),
            max_threshold=float(data.get("max_threshold", 0.99)),
            retention_days=int(data.get("retention_days", 30)),
            history_retention_days=int(data.get("history_retention_days", 90)),
            theme=str(data.get("theme", "g100")),
            auto_dismiss_after_hours=int(data.get("auto_dismiss_after_hours", 0)),
        )


__all__ = ["Settings"]
