"""Unit tests for pulse_view.py (PulseSink & PulseViewManager).

Unit-marked: no app launch, no hardware dependencies.
"""

import numpy as np
import pytest

from pulse_view import PulseSink, PulseViewManager
from processing.pulse_analyzer import PulseAnalysis, PulseFeatures

pytestmark = pytest.mark.unit


def _fake_analysis(side="left", beats=4):
    bins = 60
    return PulseAnalysis(
        side=side,
        phase=np.linspace(0.0, 1.0, bins, endpoint=False),
        template=np.ones(bins) * 2.5,
        env_min=np.ones(bins) * 2.0,
        env_max=np.ones(bins) * 3.0,
        env_p25=np.ones(bins) * 2.2,
        env_p75=np.ones(bins) * 2.8,
        live_phase=np.array([0.0, 0.2, 0.4]),
        live_value=np.array([2.0, 2.5, 3.0]),
        features=PulseFeatures(hr_bpm=72.0, amp=1.0, pi=0.4, reliable=True),
        beat_count=beats,
    )


# ── PulseSink tests ────────────────────────────────────────────────────────

def test_pulse_sink_subscribes_to_pulse_channel():
    assert PulseSink.channels == {"pulse"}


def test_pulse_sink_forwards_pulse_payload():
    seen = []
    sink = PulseSink(emit_fn=lambda s, p: seen.append((s, p)))
    pa = _fake_analysis(side="right")
    sink.consume("pulse", pa)
    assert len(seen) == 1
    side, payload = seen[0]
    assert side == "right"
    assert payload["side"] == "right"
    assert payload["beatCount"] == 4


def test_pulse_sink_ignores_other_channels():
    seen = []
    sink = PulseSink(emit_fn=lambda s, p: seen.append((s, p)))
    sink.consume("live", object())
    assert seen == []


def test_pulse_sink_has_lifecycle_hooks():
    sink = PulseSink(emit_fn=lambda s, p: None)
    sink.on_scan_start(object())  # must not raise
    sink.on_complete()            # must not raise


# ── PulseViewManager tests ─────────────────────────────────────────────────

def test_pulse_view_manager_streaming_and_asymmetry():
    emitted = []

    def _emit(side, payload):
        emitted.append((side, payload))

    manager = PulseViewManager(emit_fn=_emit, throttle_interval_sec=0.0)

    # Feed synthetic data to both left and right
    t = np.linspace(0.0, 8.0, 320, endpoint=False)
    # Left pulse: 75 bpm, amp 1.2
    y_l = -np.cos(2 * np.pi * 1.25 * t) * 0.6 + 3.0
    # Right pulse: 75 bpm, amp 1.4
    y_r = -np.cos(2 * np.pi * 1.25 * t) * 0.7 + 3.2

    manager.ingest_batch("left", t, y_l, force_emit=True)
    manager.ingest_batch("right", t, y_r, force_emit=True)

    assert len(emitted) >= 2
    sides_emitted = {item[0] for item in emitted}
    assert "left" in sides_emitted
    assert "right" in sides_emitted

    # Test asymmetry calculation
    asym = manager.compute_asymmetry()
    assert asym["shape_similarity"] is not None
    # Both are synchronized sine waves, so shape similarity r should be ~1.0
    assert asym["shape_similarity"] >= 0.95
    assert asym["amp_delta"] is not None


def test_pulse_view_manager_reset():
    emitted = []
    manager = PulseViewManager(emit_fn=lambda s, p: emitted.append(s))
    t = np.linspace(0.0, 5.0, 200)
    y = np.sin(t)
    manager.ingest_batch("left", t, y)

    manager.reset()
    assert manager._left_analyzer._last_snapshot is None
    assert manager._right_analyzer._last_snapshot is None


def test_pulse_view_manager_re_emit_snapshots():
    emitted = []
    manager = PulseViewManager(emit_fn=lambda s, p: emitted.append(s))
    t = np.linspace(0.0, 5.0, 200)
    y = np.sin(t)
    manager.ingest_batch("left", t, y, force_emit=False)
    assert len(emitted) == 0
    manager.re_emit_snapshots()
    assert len(emitted) == 1
    assert emitted[0] == "left"
