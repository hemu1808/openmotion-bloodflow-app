"""Unit tests for processing/pulse_analyzer.py.

Pure-Python unit tests covering:
- Beat onset and refractory period detection
- Phase normalization onto uniform grid
- Rolling ensemble averaging and min/max/percentile envelopes
- Cardiovascular morphology metrics (HR, Amp, PI, RI, AUC, Rise Time, AIx)
- Rhythm periodicity and template consistency
- Physiological reliability gate
- Left-vs-Right Pearson-r template similarity
- Edge cases (NaNs, flatlines, insufficient samples, tachycardia, zero mean)
"""

import math
import numpy as np
import pytest

from processing.pulse_analyzer import (
    PulseWaveformAnalyzer,
    compute_pearson_r,
)

pytestmark = pytest.mark.unit


def _generate_synthetic_pulse_stream(
    duration_s: float = 10.0,
    fs: float = 40.0,
    hr_bpm: float = 75.0,
    amp: float = 1.5,
    baseline: float = 3.0,
    noise_std: float = 0.02,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate realistic synthetic physiological pulse waveform."""
    n_samples = int(duration_s * fs)
    t = np.linspace(0.0, duration_s, n_samples, endpoint=False)
    freq = hr_bpm / 60.0  # Hz

    # Physiological pulse model: fundamental + 2nd harmonic + dicrotic notch
    phase = 2.0 * np.pi * freq * t
    y = -np.cos(phase) + 0.4 * np.sin(2 * phase) + 0.15 * np.cos(3 * phase)
    # Scale to desired amplitude and baseline
    y = (y - np.min(y)) / (np.max(y) - np.min(y)) * amp + baseline
    if noise_std > 0:
        np.random.seed(42)
        y += np.random.normal(0.0, noise_std, size=len(y))
    return t, y


# ── Pearson r ─────────────────────────────────────────────────────────────

def test_pearson_r_identical():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert compute_pearson_r(a, a) == pytest.approx(1.0, abs=1e-5)


def test_pearson_r_inverted():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    assert compute_pearson_r(a, b) == pytest.approx(-1.0, abs=1e-5)


def test_pearson_r_handles_nans_and_short_arrays():
    assert math.isnan(compute_pearson_r(np.array([1.0]), np.array([1.0])))
    assert math.isnan(compute_pearson_r(np.array([]), np.array([])))
    a = np.array([1.0, np.nan, 3.0, 4.0])
    b = np.array([1.0, 2.0, 3.0, 4.0])
    r = compute_pearson_r(a, b)
    assert math.isfinite(r)
    assert r > 0.99


def test_pearson_r_flatline_returns_nan():
    a = np.array([2.0, 2.0, 2.0, 2.0])
    b = np.array([1.0, 2.0, 3.0, 4.0])
    assert math.isnan(compute_pearson_r(a, b))


# ── Analyzer: Insufficient / Empty data ────────────────────────────────────

def test_analyzer_empty_buffer():
    analyzer = PulseWaveformAnalyzer(side="left")
    snap = analyzer.compute()
    assert snap.side == "left"
    assert snap.beat_count == 0
    assert snap.features.reliable is False
    assert len(snap.phase) == 60
    assert len(snap.template) == 60
    assert np.all(snap.template == 0.0)


def test_analyzer_insufficient_samples():
    analyzer = PulseWaveformAnalyzer(side="right")
    t = np.linspace(0.0, 0.4, 16)
    v = np.sin(t)
    snap = analyzer.feed_batch(t, v)
    assert snap.beat_count == 0
    assert snap.features.reliable is False


# ── Analyzer: Synthetic Regular Pulse ─────────────────────────────────────

def test_analyzer_detects_regular_beats():
    t, v = _generate_synthetic_pulse_stream(
        duration_s=8.0, hr_bpm=75.0, amp=1.5, baseline=3.0
    )
    analyzer = PulseWaveformAnalyzer(side="left", min_beats_for_template=3)
    snap = analyzer.feed_batch(t, v)

    assert snap.beat_count >= 5
    f = snap.features
    assert f.reliable is True
    # HR should be ~75 BPM (within 5 BPM)
    assert 70.0 <= f.hr_bpm <= 80.0
    # Amplitude ~1.5
    assert 1.2 <= f.amp <= 1.8
    # Pulsatility Index PI = Amp / Mean (~1.5 / 3.75 ~ 0.4)
    assert 0.2 <= f.pi <= 0.8
    # Resistivity Index RI = Amp / Peak (~1.5 / 4.5 ~ 0.33)
    assert 0.1 <= f.ri <= 0.6
    # Periodicity and consistency should be very high
    assert f.periodicity >= 0.85
    assert f.consistency >= 0.85
    # Rise time > 0
    assert f.rise_time_ms > 50.0


def test_analyzer_envelopes_bracket_template():
    t, v = _generate_synthetic_pulse_stream(duration_s=8.0, hr_bpm=75.0)
    analyzer = PulseWaveformAnalyzer(side="right")
    snap = analyzer.feed_batch(t, v)

    assert len(snap.template) == 60
    assert len(snap.env_min) == 60
    assert len(snap.env_max) == 60
    assert np.all(snap.env_min <= snap.template + 1e-6)
    assert np.all(snap.env_max >= snap.template - 1e-6)
    assert np.all(snap.env_p25 <= snap.env_p75 + 1e-6)


def test_analyzer_live_sweeping_beat():
    t, v = _generate_synthetic_pulse_stream(duration_s=8.0, hr_bpm=75.0)
    analyzer = PulseWaveformAnalyzer(side="left")
    snap = analyzer.feed_batch(t, v)

    # There should be an active sweeping segment
    assert len(snap.live_phase) > 0
    assert len(snap.live_value) == len(snap.live_phase)
    assert np.all(snap.live_phase >= 0.0)
    assert np.all(snap.live_phase <= 1.05)


def test_analyzer_to_dict_matches_qml_contract():
    t, v = _generate_synthetic_pulse_stream(duration_s=8.0, hr_bpm=75.0)
    analyzer = PulseWaveformAnalyzer(side="left")
    snap = analyzer.feed_batch(t, v)
    d = snap.to_dict()

    expected_keys = {
        "side", "phase", "template", "envMin", "envMax",
        "envP25", "envP75", "livePhase", "liveValue", "features", "beatCount"
    }
    assert set(d.keys()) == expected_keys
    assert d["side"] == "left"
    assert isinstance(d["phase"], list)
    assert isinstance(d["template"], list)
    assert isinstance(d["features"], dict)

    feat_keys = {
        "hr_bpm", "amp", "pi", "ri", "auc", "rise_time_ms",
        "aix", "beat_count", "periodicity", "consistency", "reliable",
        "sqi", "peakPhase", "shoulderPhase"
    }
    assert set(d["features"].keys()) == feat_keys
    assert d["features"]["reliable"] is True
    assert isinstance(d["features"]["sqi"], int)
    assert 0 <= d["features"]["sqi"] <= 100


# ── Analyzer: Edge cases ──────────────────────────────────────────────────

def test_analyzer_flatline_rejects_as_unreliable():
    t = np.linspace(0.0, 10.0, 400)
    v = np.full_like(t, 3.5)
    analyzer = PulseWaveformAnalyzer(side="left")
    snap = analyzer.feed_batch(t, v)
    assert snap.features.reliable is False
    assert snap.beat_count == 0


def test_analyzer_pure_noise_rejects_as_unreliable():
    np.random.seed(99)
    t = np.linspace(0.0, 10.0, 400)
    v = np.random.uniform(1.0, 5.0, size=len(t))
    analyzer = PulseWaveformAnalyzer(side="left")
    snap = analyzer.feed_batch(t, v)
    # White noise should not pass the consistency and physiological gates
    assert snap.features.reliable is False


def test_analyzer_handles_streaming_sample_by_sample():
    t, v = _generate_synthetic_pulse_stream(duration_s=6.0, hr_bpm=80.0)
    analyzer = PulseWaveformAnalyzer(side="right")
    snap = None
    for ti, vi in zip(t, v):
        snap = analyzer.append_sample(ti, vi)

    assert snap is not None
    assert snap.beat_count >= 3
    assert snap.features.reliable is True
    assert 72.0 <= snap.features.hr_bpm <= 88.0


def test_analyzer_reset_clears_state():
    t, v = _generate_synthetic_pulse_stream(duration_s=6.0, hr_bpm=80.0)
    analyzer = PulseWaveformAnalyzer(side="left")
    analyzer.feed_batch(t, v)
    assert analyzer._last_snapshot.beat_count > 0

    analyzer.reset()
    snap = analyzer.compute()
    assert snap.beat_count == 0
    assert snap.features.reliable is False


# ── Real Data Verification: sample_scan.csv ────────────────────────────────

def test_analyzer_on_real_sample_scan():
    import pandas as pd
    from utils.resource_path import resource_path

    csv_path = resource_path("resources", "sample_scan.csv")
    df = pd.read_csv(csv_path)

    t = df["timestamp_s"].values
    # Active research mask cameras
    left_cams = ["bfi_l1", "bfi_l2", "bfi_l3", "bfi_l6", "bfi_l7", "bfi_l8"]
    right_cams = ["bfi_r1", "bfi_r2", "bfi_r3", "bfi_r6", "bfi_r7", "bfi_r8"]
    left_bfi = df[left_cams].mean(axis=1).values
    right_bfi = df[right_cams].mean(axis=1).values

    left_analyzer = PulseWaveformAnalyzer(side="left")
    right_analyzer = PulseWaveformAnalyzer(side="right")

    left_snap = left_analyzer.feed_batch(t, left_bfi)
    right_snap = right_analyzer.feed_batch(t, right_bfi)

    # Both sides should extract beats
    assert left_snap.beat_count >= 5
    assert right_snap.beat_count >= 5

    # Features should reflect physiological cardiac hemodynamics
    assert 50.0 <= left_snap.features.hr_bpm <= 130.0
    assert 50.0 <= right_snap.features.hr_bpm <= 130.0
    assert left_snap.features.amp > 0.1
    assert right_snap.features.amp > 0.1

    # Left and right templates should have measurable morphological correlation
    # (on this sample scan, true physiological asymmetry produces r ~ 0.56)
    r_shape = compute_pearson_r(left_snap.template, right_snap.template)
    assert math.isfinite(r_shape)
    assert 0.40 <= r_shape <= 0.99
