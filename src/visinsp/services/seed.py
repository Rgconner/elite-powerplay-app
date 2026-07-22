"""
Sample data seeder.

Generates a small set of synthetic reference + capture images so the
WSL mock mode has something to show right after install.

Lives inside the package so both :mod:`visinsp.services.cli` and the
top-level ``scripts/seed-sample-data.py`` shim can import the same
function.

Creates:

* ``data/references/reference_good.png``  (synthetic "good" part)
* ``data/references/reference_defect.png`` (synthetic "defect" part)
* ``data/samples/capture_00.png`` ... ``capture_04.png`` (varying captures)
* ``data/samples/capture_defect_00.png``   (deliberately different)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from visinsp.paths import Paths, ensure_data_dirs

log = logging.getLogger(__name__)


def _make_synthetic_part(width: int = 640, height: int = 480, defect: bool = False, seed: int = 0) -> np.ndarray:
    """Generate a deterministic synthetic part image (so tests are reproducible)."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 200, dtype=np.uint8)  # light gray background

    # A central "part" rectangle
    cv2.rectangle(img, (width // 4, height // 4), (3 * width // 4, 3 * height // 4), (60, 60, 60), 3)

    # A pattern of small circles (like rivets / holes)
    for x in range(width // 4 + 40, 3 * width // 4, 60):
        for y in range(height // 4 + 40, 3 * height // 4, 60):
            color = (40, 40, 40) if not defect else (20, 20, 20)
            cv2.circle(img, (x, y), 8, color, -1)
            if defect and (x, y) == (width // 4 + 40, height // 4 + 40):
                # One missing rivet (the "defect")
                cv2.circle(img, (x, y), 10, (200, 200, 200), -1)

    # A serial number text in the corner (so it changes between references)
    text = f"SN-{seed:04d}"
    if defect:
        text += " DEFECT"
    cv2.putText(img, text, (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    # Add a tiny bit of noise so captures differ slightly from the reference
    noise = rng.integers(-8, 8, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def seed(paths: Paths, count: int = 5) -> None:
    """Generate the sample images into the configured directories."""
    ensure_data_dirs(paths)

    # Two reference images
    good = _make_synthetic_part(defect=False, seed=42)
    bad = _make_synthetic_part(defect=True, seed=43)

    ref_good_path = paths.references_dir / "reference_good.png"
    ref_bad_path = paths.references_dir / "reference_defect.png"
    cv2.imwrite(str(ref_good_path), good)
    cv2.imwrite(str(ref_bad_path), bad)
    log.info("wrote %s", ref_good_path)
    log.info("wrote %s", ref_bad_path)

    # Several captures: mostly good, one defective
    for i in range(count):
        img = _make_synthetic_part(defect=False, seed=1000 + i)
        out = paths.sample_images_dir / f"capture_{i:02d}.png"
        cv2.imwrite(str(out), img)
        log.info("wrote %s", out)

    img = _make_synthetic_part(defect=True, seed=9999)
    out = paths.sample_images_dir / "capture_defect_00.png"
    cv2.imwrite(str(out), img)
    log.info("wrote %s", out)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Visual Inspector sample data.")
    parser.add_argument("--count", type=int, default=5, help="How many sample captures to create.")
    args = parser.parse_args(argv)

    # Configure minimal logging so the function works whether called from
    # the CLI or directly as a script.
    if not log.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    from visinsp.config import load_config
    from visinsp.paths import resolve_paths

    cfg = load_config()
    paths = resolve_paths(cfg)
    seed(paths, count=args.count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
