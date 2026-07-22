"""Tests for the mock GPIO backend."""

import tempfile
import time
from pathlib import Path

import pytest

from visinsp.hardware import GpioMock
from visinsp.models import Pin, PinEdge


def make_pin(pid="p1", bcm=17, edge=PinEdge.FALLING, debounce_ms=10):
    return Pin(id=pid, bcm=bcm, name=pid, edge=edge, debounce_ms=debounce_ms, active_low=True)


def test_setup_assigns_default_level():
    m = GpioMock()
    m.setup([make_pin()])
    assert m.read("p1") == 1  # active-low default HIGH


def test_simulate_edge_falls_through_debounce():
    m = GpioMock()
    m.setup([make_pin(debounce_ms=50)])
    m.simulate_edge("p1", 0)  # active-low: logical 1, falling edge
    # wait_for_edge should return immediately
    pid = m.wait_for_edge(["p1"], timeout_s=0.5)
    assert pid == "p1"


def test_debounce_suppresses_bursts():
    m = GpioMock()
    m.setup([make_pin(debounce_ms=200)])
    # First edge is delivered
    m.simulate_edge("p1", 0)
    pid1 = m.wait_for_edge(["p1"], timeout_s=0.2)
    assert pid1 == "p1"
    # Second edge inside the debounce window is suppressed
    m.simulate_edge("p1", 1)
    m.simulate_edge("p1", 0)
    pid2 = m.wait_for_edge(["p1"], timeout_s=0.2)
    assert pid2 is None


def test_toggle_flips_level():
    m = GpioMock()
    m.setup([make_pin()])
    initial = m.read("p1")
    new = m.toggle("p1")
    assert new == (0 if initial == 1 else 1)
    assert m.read("p1") == new


def test_persistence_round_trip(tmp_path):
    p = tmp_path / "mock_pins.json"
    m1 = GpioMock(persist_path=p)
    m1.setup([make_pin()])
    m1.write("p1", 0)
    m2 = GpioMock(persist_path=p)
    m2.setup([make_pin()])
    assert m2.read("p1") == 0
