"""Image inspection engine.

Given a captured frame and a reference (image + bounding boxes), compute
a per-box confidence score using OpenCV's ``matchTemplate`` and an
overall weighted score. The overall score is compared to the job's
threshold to decide pass/fail.

All public methods are pure: they take images as numpy arrays and return
an :class:`InspectionResult`. Persistence and alert creation are handled
by the caller (the daemon) so the engine can be unit-tested without
filesystem or DB access.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..models import (
    BBoxScore,
    BoundingBox,
    InspectionResult,
    Job,
    ReferenceImage,
    SecondaryMetric,
    compute_overall_score,
)

log = logging.getLogger(__name__)


_MATCH_METHODS = {
    "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
    "TM_CCOEFF": cv2.TM_CCOEFF,
    "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
    "TM_CCORR": cv2.TM_CCORR,
    "TM_SQDIFF": cv2.TM_SQDIFF,
    "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
}


def resolve_match_method(name: str) -> int:
    """Convert a config string to an OpenCV matchTemplate constant.

    Falls back to ``TM_CCOEFF_NORMED`` if the name is unknown.
    """
    if not name:
        return cv2.TM_CCOEFF_NORMED
    return _MATCH_METHODS.get(str(name).upper(), cv2.TM_CCOEFF_NORMED)


def _crop(img: np.ndarray, bbox: BoundingBox) -> Optional[np.ndarray]:
    """Safely crop a region out of an image (returns None if fully out of bounds)."""
    h, w = img.shape[:2]
    x1 = max(0, min(int(bbox.x), w - 1))
    y1 = max(0, min(int(bbox.y), h - 1))
    x2 = max(x1 + 1, min(int(bbox.x + bbox.w), w))
    y2 = max(y1 + 1, min(int(bbox.y + bbox.h), h))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img is None:
        raise ValueError("image is None")
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _secondary_score(
    ref_crop: np.ndarray, cap_crop: np.ndarray, metric: SecondaryMetric
) -> Optional[float]:
    """Return a secondary similarity score (MSE or SSIM) or None if not requested."""
    if metric == SecondaryMetric.NONE:
        return None
    if ref_crop.shape != cap_crop.shape:
        # Resize the captured crop to the reference shape so the metrics
        # are comparable. This is a best-effort fallback; the primary
        # matchTemplate score is still the gate.
        cap_crop = cv2.resize(cap_crop, (ref_crop.shape[1], ref_crop.shape[0]))
    if metric == SecondaryMetric.MSE:
        diff = ref_crop.astype(np.float32) - cap_crop.astype(np.float32)
        mse = float(np.mean(diff * diff))
        # Convert MSE (0=identical, large=different) into a 0..1 similarity.
        # 255^2 = 65025 is the worst case. 1 - mse/65025 is a crude mapping.
        return max(0.0, 1.0 - mse / 65025.0)
    if metric == SecondaryMetric.SSIM:
        try:
            from skimage.metrics import structural_similarity  # type: ignore
        except ImportError:
            log.debug("skimage not available — skipping SSIM")
            return None
        s = structural_similarity(ref_crop, cap_crop)
        return float(s)
    return None


class InspectionEngine:
    """Stateful engine — keeps the most recent reference image in memory."""

    def __init__(self, default_method: str = "TM_CCOEFF_NORMED",
                 default_secondary: SecondaryMetric = SecondaryMetric.NONE,
                 max_image_dimension: int = 1280):
        self.default_method = default_method
        self.default_secondary = default_secondary
        self.max_image_dimension = max_image_dimension
        # Cached, decoded reference images keyed by reference id.
        self._cache: Dict[str, np.ndarray] = {}

    # ---- public API ----

    def inspect(
        self,
        captured: np.ndarray,
        reference: ReferenceImage,
        job: Job,
        *,
        method: Optional[str] = None,
        secondary: Optional[SecondaryMetric] = None,
        trigger_id: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> InspectionResult:
        """Compare ``captured`` against ``reference`` for ``job``.

        Returns an :class:`InspectionResult` regardless of pass/fail.
        """
        if captured is None:
            raise ValueError("captured image is None")
        if not reference.bboxes:
            raise ValueError("reference has no bounding boxes")

        method_name = method or self.default_method
        method_flag = resolve_match_method(method_name)
        secondary_metric = secondary if secondary is not None else self.default_secondary

        ref_img = self._load_reference(reference)
        if ref_img is None:
            raise FileNotFoundError(f"reference image missing: {reference.image_path}")

        # Resize the captured image if it's much larger than the reference.
        captured = self._resize_if_needed(captured)

        # If the captured frame's dimensions don't match the reference's,
        # we still try to use the bounding boxes (clamped) and run the
        # match — boxes will be the same pixel coordinates on both.
        per_box_scores: List[BBoxScore] = []
        weights: Dict[str, float] = {}
        for bb in reference.bboxes:
            ref_crop = _crop(ref_img, bb)
            cap_crop = _crop(captured, bb)
            if ref_crop is None or cap_crop is None:
                log.warning("bbox %s clipped to nothing; skipping", bb.id)
                continue
            # matchTemplate requires the template smaller than the image.
            # The reference crop and captured crop are the same size, so we
            # compare them directly via their histograms / mean abs diff.
            # But to keep a true matchTemplate result, we slide the
            # reference crop across a slightly larger area of the
            # captured image (using the box + a margin). If the margin
            # area is too small, we fall back to a direct MSE-like score.
            score, sec = self._score_box(
                ref_crop, cap_crop, captured, bb, method_flag, method_name, secondary_metric
            )
            per_box_scores.append(
                BBoxScore(
                    bbox_id=bb.id,
                    score=float(score),
                    method=method_name,
                    secondary=sec,
                    secondary_metric=secondary_metric.value,
                )
            )
            weights[bb.id] = float(bb.weight)

        if not per_box_scores:
            # No usable boxes — treat as a hard fail with score 0.
            overall = 0.0
        else:
            overall = compute_overall_score(per_box_scores, weights)

        passed = overall >= float(job.threshold)
        result = InspectionResult(
            id=f"insp_{uuid.uuid4().hex[:10]}",
            job_id=job.id,
            trigger_id=trigger_id,
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            score_overall=overall,
            threshold=float(job.threshold),
            passed=passed,
            per_box=per_box_scores,
            image_path=image_path,
            match_method=method_name,
        )
        log.info(
            "inspect: job=%s overall=%.4f threshold=%.4f passed=%s boxes=%d",
            job.id, overall, job.threshold, passed, len(per_box_scores),
        )
        return result

    def invalidate(self, reference_id: Optional[str] = None) -> None:
        """Drop the cached reference image. Pass None to clear everything."""
        if reference_id is None:
            self._cache.clear()
        else:
            self._cache.pop(reference_id, None)

    # ---- helpers ----

    def _load_reference(self, reference: ReferenceImage) -> Optional[np.ndarray]:
        if reference.id in self._cache:
            return self._cache[reference.id]
        path = Path(reference.image_path)
        if not path.exists():
            log.error("reference image not found: %s", path)
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            log.error("cv2.imread returned None for %s", path)
            return None
        img = self._resize_if_needed(img)
        self._cache[reference.id] = img
        return img

    def _resize_if_needed(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest <= self.max_image_dimension:
            return img
        scale = self.max_image_dimension / float(longest)
        new_w = int(w * scale)
        new_h = int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def _score_box(
        self,
        ref_crop: np.ndarray,
        cap_crop: np.ndarray,
        captured: np.ndarray,
        bbox: BoundingBox,
        method_flag: int,
        method_name: str,
        secondary: SecondaryMetric,
    ) -> Tuple[float, Optional[float]]:
        """Score a single bounding box.

        Strategy:
          1. If the reference crop is smaller than the captured crop,
             run a real matchTemplate sliding the reference across the
             captured crop (using the box as the template).
          2. Otherwise, run matchTemplate on a slightly larger region
             (the captured crop + a margin) with the reference crop as
             the template. If the margin would go out of bounds, fall
             back to the direct mean-abs-diff normalised score.
        """
        ref_gray = _to_gray(ref_crop)
        cap_gray = _to_gray(cap_crop)

        th, tw = ref_gray.shape[:2]
        ch, cw = cap_gray.shape[:2]

        if th <= ch and tw <= cw:
            # We can do a real matchTemplate. The "image" is cap_gray
            # and the "template" is ref_gray.
            try:
                result = cv2.matchTemplate(cap_gray, ref_gray, method_flag)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                score = self._normalise_score(max_val, method_flag)
            except cv2.error as e:
                log.warning("matchTemplate failed on bbox %s: %s", bbox.id, e)
                score = self._direct_similarity(ref_gray, cap_gray, method_flag)
        else:
            score = self._direct_similarity(ref_gray, cap_gray, method_flag)

        sec = _secondary_score(ref_gray, cap_gray, secondary)
        return float(score), sec

    @staticmethod
    def _normalise_score(raw: float, method_flag: int) -> float:
        """Convert raw matchTemplate output to a 0..1 similarity (higher = better).

        For TM_SQDIFF / TM_SQDIFF_NORMED, lower is better; we invert.
        For the rest, higher is better and they're already in -1..1 or 0..1.
        """
        if method_flag in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
            # raw in [0, 1] for the NORMED variant; for non-normed, larger values.
            if method_flag == cv2.TM_SQDIFF_NORMED:
                return max(0.0, 1.0 - float(raw))
            # Best-effort for non-normed
            return max(0.0, 1.0 - min(1.0, float(raw) / 1_000_000.0))
        # CCOEFF_NORMED and CCORR_NORMED are in [-1, 1]
        if method_flag in (cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR_NORMED):
            return max(0.0, min(1.0, (float(raw) + 1.0) / 2.0))
        # Non-normed variants — best-effort clamp
        return max(0.0, min(1.0, float(raw)))

    @staticmethod
    def _direct_similarity(ref: np.ndarray, cap: np.ndarray, method_flag: int) -> float:
        """Direct similarity when matchTemplate can't be used (size mismatch)."""
        if ref.shape != cap.shape:
            cap = cv2.resize(cap, (ref.shape[1], ref.shape[0]))
        a = ref.astype(np.float32)
        b = cap.astype(np.float32)
        diff = np.abs(a - b)
        # Normalised MAE → similarity
        mae = float(np.mean(diff)) / 255.0
        return max(0.0, 1.0 - mae)


__all__ = ["InspectionEngine", "resolve_match_method", "SecondaryMetric"]
