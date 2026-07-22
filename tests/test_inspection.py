"""Tests for the inspection engine."""

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from visinsp.core import InspectionEngine
from visinsp.models import BoundingBox, Job, ReferenceImage


@pytest.fixture
def fixture_pair(tmp_path):
    """Create a reference image + capture, both with the same content."""
    rng = np.random.default_rng(42)
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (250, 250), (60, 60, 60), 3)
    for x in range(70, 250, 40):
        for y in range(70, 250, 40):
            cv2.circle(img, (x, y), 6, (40, 40, 40), -1)
    ref_path = tmp_path / "ref.png"
    cap_path = tmp_path / "cap.png"
    cv2.imwrite(str(ref_path), img)
    # Slightly noisy capture (same content + a little noise)
    noise = rng.integers(-3, 3, img.shape, dtype=np.int16)
    noisy = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(cap_path), noisy)
    return ref_path, cap_path, img, noisy


def test_identical_images_score_high(tmp_path):
    ref_path, cap_path, ref, cap = (
        pytest.fixture(fixture_pair).__func__(tmp_path)
        if False else None, None, None, None
    )
    # Manual setup for clarity
    rng = np.random.default_rng(42)
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (250, 250), (60, 60, 60), 3)
    ref_path = tmp_path / "ref.png"
    cv2.imwrite(str(ref_path), img)
    engine = InspectionEngine()
    ref_img = ReferenceImage(
        id="r1", name="ref", camera_id="c", image_path=str(ref_path),
        bboxes=[BoundingBox(id="b1", x=50, y=50, w=200, h=200)],
    )
    job = Job(id="j1", name="j", reference_id="r1", camera_id="c", threshold=0.5)
    result = engine.inspect(img, ref_img, job, image_path=str(ref_path))
    assert result.passed is True
    assert result.score_overall > 0.5


def test_modified_image_scores_lower(tmp_path):
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (250, 250), (60, 60, 60), 3)
    for x in range(70, 250, 40):
        for y in range(70, 250, 40):
            cv2.circle(img, (x, y), 6, (40, 40, 40), -1)
    ref_path = tmp_path / "ref.png"
    cv2.imwrite(str(ref_path), img)

    # Capture is very different
    diff = np.full((300, 300, 3), 50, dtype=np.uint8)
    cv2.rectangle(diff, (50, 50), (250, 250), (10, 10, 10), 3)
    cap_path = tmp_path / "cap.png"
    cv2.imwrite(str(cap_path), diff)

    engine = InspectionEngine()
    ref_img = ReferenceImage(
        id="r1", name="ref", camera_id="c", image_path=str(ref_path),
        bboxes=[BoundingBox(id="b1", x=50, y=50, w=200, h=200)],
    )
    job = Job(id="j1", name="j", reference_id="r1", camera_id="c", threshold=0.9)
    result = engine.inspect(diff, ref_img, job, image_path=str(cap_path))
    assert result.passed is False


def test_missing_bbox_raises():
    engine = InspectionEngine()
    ref = ReferenceImage(id="r1", name="r", camera_id="c", image_path="/none.png", bboxes=[])
    job = Job(id="j1", name="j", reference_id="r1", camera_id="c")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        engine.inspect(img, ref, job)
