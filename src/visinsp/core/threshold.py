"""Threshold auto-adjustment logic.

The confidence threshold for each job is nudged up or down by a small step
(``job.threshold_step``) based on operator verdicts on dismissed alerts:

* ``valid``           — no change.
* ``false_positive``  — raise threshold (be more strict).
* ``false_negative``  — lower threshold (be more permissive).

The new value is always clamped to ``[settings.min_threshold, settings.max_threshold]``.
"""

from __future__ import annotations

import logging
from typing import Tuple

from ..models import AlertVerdict

log = logging.getLogger(__name__)


def clamp_threshold(
    value: float,
    min_value: float,
    max_value: float,
) -> float:
    """Clamp a threshold value to the configured bounds."""
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def apply_verdict(
    current_threshold: float,
    step: float,
    verdict: AlertVerdict,
    min_value: float,
    max_value: float,
) -> Tuple[float, bool]:
    """Return ``(new_threshold, changed)`` for the given verdict.

    * ``valid``          → unchanged.
    * ``false_positive`` → ``current + step`` (clamped).
    * ``false_negative`` → ``current - step`` (clamped).
    * ``pending``        → unchanged.
    """
    if verdict == AlertVerdict.VALID or verdict == AlertVerdict.PENDING:
        return current_threshold, False

    if verdict == AlertVerdict.FALSE_POSITIVE:
        target = current_threshold + step
        direction = "raise"
    elif verdict == AlertVerdict.FALSE_NEGATIVE:
        target = current_threshold - step
        direction = "lower"
    else:
        log.warning("apply_verdict: unknown verdict %r", verdict)
        return current_threshold, False

    new_value = clamp_threshold(target, min_value, max_value)
    if abs(new_value - current_threshold) < 1e-9:
        log.info("threshold: %s by %.4f requested but already at bound %.4f",
                 direction, step, new_value)
        return new_value, False
    log.info("threshold: %s by %.4f → %.4f (was %.4f)",
             direction, step, new_value, current_threshold)
    return new_value, True


__all__ = ["apply_verdict", "clamp_threshold"]
