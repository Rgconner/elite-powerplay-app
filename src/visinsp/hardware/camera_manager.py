"""Camera manager — enumerates cameras and routes captures.

Tries the real OpenCV backend first; falls back to the sample-image
backend if no cameras are detected and ``wsl_sample_fallback`` is True
(config-driven).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .camera_backend import (
    CameraBackend,
    OpenCVCameraBackend,
    SampleImageCameraBackend,
)

log = logging.getLogger(__name__)


@dataclass
class CameraInfo:
    """A single camera's configuration + status."""

    id: str
    name: str
    device_index: int
    available: bool = True
    is_sample_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "device_index": self.device_index,
            "available": self.available,
            "is_sample_fallback": self.is_sample_fallback,
        }


class CameraManager:
    """Thread-safe camera manager.

    Holds one backend at a time (real or fallback). ``list_cameras`` reads
    the static config and pokes each device; ``capture`` writes to the
    configured captures directory and returns the in-memory frame.
    """

    def __init__(
        self,
        config,
        paths,
    ):
        self._lock = threading.RLock()
        self.config = config
        self.paths = paths
        probe_max = int(config.get("camera.probe_max_index", 4))
        capture_timeout = float(config.get("camera.capture_timeout_s", 5.0))
        self._opencv = OpenCVCameraBackend(probe_max_index=probe_max, capture_timeout_s=capture_timeout)
        self._sample = SampleImageCameraBackend(samples_dir=paths.sample_images_dir)
        self._active_backend: CameraBackend = self._opencv
        self._cameras: List[CameraInfo] = []
        self._refresh_cameras()

    # ---- enumeration ----

    def _refresh_cameras(self) -> None:
        with self._lock:
            cfg_cams = self.config.get("cameras", []) or []
            opencv_indices = set(self._opencv.list_cameras())
            use_fallback = bool(self.config.get("camera.wsl_sample_fallback", True))
            fallback_active = not opencv_indices and use_fallback
            self._active_backend = self._sample if fallback_active else self._opencv
            out: List[CameraInfo] = []
            for c in cfg_cams:
                dev = int(c.get("device_index", 0))
                if fallback_active:
                    available = dev == 0
                    is_fb = True
                else:
                    available = dev in opencv_indices
                    is_fb = False
                out.append(CameraInfo(
                    id=str(c.get("id") or f"cam_{dev}"),
                    name=str(c.get("name") or f"Camera {dev}"),
                    device_index=dev,
                    available=available,
                    is_sample_fallback=is_fb,
                ))
            self._cameras = out
            if fallback_active:
                log.info("camera: no hardware cameras detected, using sample-image fallback")
            else:
                log.info("camera: detected device indices %s", sorted(opencv_indices))

    def list_cameras(self) -> List[CameraInfo]:
        with self._lock:
            return list(self._cameras)

    def refresh(self) -> None:
        self._refresh_cameras()

    # ---- capture ----

    def capture(
        self,
        camera_id: str,
        save: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Capture from a named camera.

        ``save`` defaults to ``config.inspection.save_captures``.
        Returns a dict with ``frame`` (ndarray | None), ``path`` (Path | None),
        ``width`` and ``height``.
        """
        with self._lock:
            cam = next((c for c in self._cameras if c.id == camera_id), None)
            if cam is None:
                # Allow direct device-index lookup by integer.
                try:
                    dev = int(camera_id)
                    cam = CameraInfo(id=f"cam_{dev}", name=f"Camera {dev}", device_index=dev)
                except (TypeError, ValueError):
                    return {"frame": None, "path": None, "error": f"unknown camera: {camera_id}"}

        if save is None:
            save = bool(self.config.get("inspection.save_captures", True))

        # Persist path (only if save=True)
        save_path: Optional[Path] = None
        if save:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = self.paths.captures_dir / f"{cam.id}_{stamp}_{uuid.uuid4().hex[:6]}.jpg"

        frame = self._active_backend.capture(cam.device_index, save_path=save_path)
        if frame is None:
            return {"frame": None, "path": None, "error": "capture failed"}
        h, w = frame.shape[:2]
        return {
            "frame": frame,
            "path": save_path,
            "width": w,
            "height": h,
            "camera_id": cam.id,
        }


__all__ = ["CameraManager", "CameraInfo"]
