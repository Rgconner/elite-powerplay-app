"""Camera capture backend.

Wraps OpenCV's ``VideoCapture`` with a few niceties:

* idempotent open/close
* timeout-bounded capture
* optional WSL fallback to a sample-image directory

The manager lives in :mod:`camera_manager`; this module only defines
the backend interface and the OpenCV implementation.
"""

from __future__ import annotations

import abc
import logging
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class CameraBackend(abc.ABC):
    """Abstract camera backend."""

    name: str = "abstract"

    @abc.abstractmethod
    def list_cameras(self) -> List[int]:
        """Return the device indices that look like working cameras."""

    @abc.abstractmethod
    def capture(self, device_index: int, save_path: Optional[Path] = None) -> Optional[np.ndarray]:
        """Capture a single frame; optionally write it to ``save_path``."""


class OpenCVCameraBackend(CameraBackend):
    """OpenCV VideoCapture wrapper."""

    name = "opencv"

    def __init__(self, probe_max_index: int = 4, capture_timeout_s: float = 5.0):
        self.probe_max_index = max(1, int(probe_max_index))
        self.capture_timeout_s = max(0.5, float(capture_timeout_s))

    def list_cameras(self) -> List[int]:
        found: List[int] = []
        for i in range(self.probe_max_index):
            cap = cv2.VideoCapture(i)
            try:
                if cap.isOpened():
                    found.append(i)
            finally:
                cap.release()
        return found

    def capture(self, device_index: int, save_path: Optional[Path] = None) -> Optional[np.ndarray]:
        cap = cv2.VideoCapture(int(device_index))
        if not cap.isOpened():
            log.error("capture: cannot open camera %s", device_index)
            return None
        deadline = time.monotonic() + self.capture_timeout_s
        frame = None
        try:
            # Some webcams need a few warm-up frames.
            while time.monotonic() < deadline:
                ok, fr = cap.read()
                if ok and fr is not None:
                    frame = fr
                    break
                time.sleep(0.05)
        finally:
            cap.release()
        if frame is None:
            log.error("capture: no frame from camera %s within %.1fs",
                      device_index, self.capture_timeout_s)
            return None
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                cv2.imwrite(str(save_path), frame)
            except cv2.error as e:
                log.warning("capture: could not save to %s: %s", save_path, e)
        return frame


class SampleImageCameraBackend(CameraBackend):
    """Fallback that returns a sample image from a directory.

    Used by WSL when no real camera is detected. Cycles through the
    available images so repeated captures get different content.
    """

    name = "samples"

    def __init__(self, samples_dir: Path):
        self.samples_dir = Path(samples_dir)
        self._index = 0

    def list_cameras(self) -> List[int]:
        return [0] if self._sample_files() else []

    def _sample_files(self) -> List[Path]:
        if not self.samples_dir.exists():
            return []
        exts = (".jpg", ".jpeg", ".png", ".bmp")
        return sorted(p for p in self.samples_dir.iterdir() if p.suffix.lower() in exts)

    def capture(self, device_index: int, save_path: Optional[Path] = None) -> Optional[np.ndarray]:
        files = self._sample_files()
        if not files:
            log.warning("sample-fallback: no images in %s", self.samples_dir)
            return None
        src = files[self._index % len(files)]
        self._index += 1
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            log.warning("sample-fallback: cv2.imread failed for %s", src)
            return None
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                cv2.imwrite(str(save_path), img)
            except cv2.error as e:
                log.warning("sample-fallback: could not save to %s: %s", save_path, e)
        log.debug("sample-fallback: served %s", src)
        return img


__all__ = ["CameraBackend", "OpenCVCameraBackend", "SampleImageCameraBackend"]
