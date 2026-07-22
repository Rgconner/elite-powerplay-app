"""Tests for the threshold auto-adjust logic."""

from visinsp.core.threshold import apply_verdict, clamp_threshold
from visinsp.models import AlertVerdict


def test_clamp_threshold_lower():
    assert clamp_threshold(0.3, 0.5, 0.99) == 0.5


def test_clamp_threshold_upper():
    assert clamp_threshold(1.5, 0.5, 0.99) == 0.99


def test_clamp_threshold_in_range():
    assert clamp_threshold(0.85, 0.5, 0.99) == 0.85


def test_apply_verdict_valid_no_change():
    new, changed = apply_verdict(0.85, 0.005, AlertVerdict.VALID, 0.5, 0.99)
    assert new == 0.85
    assert changed is False


def test_apply_verdict_false_positive_raises():
    new, changed = apply_verdict(0.85, 0.01, AlertVerdict.FALSE_POSITIVE, 0.5, 0.99)
    assert new == 0.86
    assert changed is True


def test_apply_verdict_false_negative_lowers():
    new, changed = apply_verdict(0.85, 0.01, AlertVerdict.FALSE_NEGATIVE, 0.5, 0.99)
    assert new == 0.84
    assert changed is True


def test_apply_verdict_clamps_at_max():
    new, changed = apply_verdict(0.99, 0.05, AlertVerdict.FALSE_POSITIVE, 0.5, 0.99)
    assert new == 0.99
    assert changed is False


def test_apply_verdict_clamps_at_min():
    new, changed = apply_verdict(0.50, 0.05, AlertVerdict.FALSE_NEGATIVE, 0.5, 0.99)
    assert new == 0.5
    assert changed is False


def test_apply_verdict_pending_no_change():
    new, changed = apply_verdict(0.85, 0.01, AlertVerdict.PENDING, 0.5, 0.99)
    assert new == 0.85
    assert changed is False


def test_apply_verdict_tiny_step():
    """Slightly-up step from a False Positive doesn't oscillate wildly."""
    new, changed = apply_verdict(0.8500, 0.005, AlertVerdict.FALSE_POSITIVE, 0.5, 0.99)
    assert abs(new - 0.855) < 1e-9
    assert changed is True
