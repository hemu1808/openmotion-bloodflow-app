"""Pulse-waveform and hemispheric asymmetry analysis for hemodynamics.

Pure-Python, NumPy-based engine for real-time cardiac beat detection, phase
normalization, rolling ensemble template extraction, morphology metrics,
and left-vs-right bilateral asymmetry.

Zero GUI/hardware dependencies — runnable in CLI, pytest, or embedded in Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class PulseFeatures:
    """Cardiovascular morphology metrics for one ensemble template."""

    hr_bpm: float = float("nan")
    amp: float = float("nan")
    pi: float = float("nan")
    ri: float = float("nan")
    auc: float = float("nan")
    rise_time_ms: float = float("nan")
    aix: float = float("nan")
    beat_count: int = 0
    periodicity: float = float("nan")
    consistency: float = float("nan")
    sqi: int = 0
    peak_phase: float = float("nan")
    shoulder_phase: float = float("nan")
    reliable: bool = False

    def to_dict(self) -> Dict[str, object]:
        """Convert to QVariant-friendly dictionary for QML."""
        return {
            "hr_bpm": (
                self.hr_bpm if math.isfinite(self.hr_bpm) else None
            ),
            "amp": self.amp if math.isfinite(self.amp) else None,
            "pi": self.pi if math.isfinite(self.pi) else None,
            "ri": self.ri if math.isfinite(self.ri) else None,
            "auc": self.auc if math.isfinite(self.auc) else None,
            "rise_time_ms": (
                self.rise_time_ms if math.isfinite(self.rise_time_ms) else None
            ),
            "aix": self.aix if math.isfinite(self.aix) else None,
            "beat_count": self.beat_count,
            "periodicity": (
                self.periodicity if math.isfinite(self.periodicity) else None
            ),
            "consistency": (
                self.consistency if math.isfinite(self.consistency) else None
            ),
            "sqi": int(self.sqi),
            "peakPhase": (
                self.peak_phase if math.isfinite(self.peak_phase) else None
            ),
            "shoulderPhase": (
                self.shoulder_phase
                if math.isfinite(self.shoulder_phase)
                else None
            ),
            "reliable": bool(self.reliable),
        }


@dataclass
class PulseAnalysis:
    """Ensemble pulse snapshot for one sensor side (left or right)."""

    side: str
    phase: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    template: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    env_min: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    env_max: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    env_p25: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    env_p75: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    live_phase: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    live_value: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    features: PulseFeatures = field(default_factory=PulseFeatures)
    beat_count: int = 0

    def to_dict(self) -> Dict[str, object]:
        """Convert to dictionary matching QML PulseCanvas/PulseStatsPanel."""
        return {
            "side": self.side,
            "phase": [float(x) for x in self.phase],
            "template": [float(x) for x in self.template],
            "envMin": [float(x) for x in self.env_min],
            "envMax": [float(x) for x in self.env_max],
            "envP25": [float(x) for x in self.env_p25],
            "envP75": [float(x) for x in self.env_p75],
            "livePhase": [float(x) for x in self.live_phase],
            "liveValue": [float(x) for x in self.live_value],
            "features": self.features.to_dict(),
            "beatCount": int(self.beat_count),
        }


def compute_pearson_r(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Pearson correlation coefficient between two 1D sequences."""
    if len(a) != len(b) or len(a) < 2:
        return float("nan")
    valid = np.isfinite(a) & np.isfinite(b)
    if np.sum(valid) < 2:
        return float("nan")
    va = a[valid]
    vb = b[valid]
    s_a = float(np.std(va))
    s_b = float(np.std(vb))
    if s_a <= 1e-12 or s_b <= 1e-12:
        return float("nan")
    cov = float(np.mean((va - np.mean(va)) * (vb - np.mean(vb))))
    r = cov / (s_a * s_b)
    return float(np.clip(r, -1.0, 1.0))


class PulseWaveformAnalyzer:
    """Extracts beats, rolling ensemble templates, and morphology stats.

    Operates on a continuous 1D stream of blood flow index (BFI) samples
    for a given side.
    """

    def __init__(
        self,
        side: str,
        phase_bins: int = 60,
        min_beats_for_template: int = 3,
        max_beats_in_ensemble: int = 10,
        nominal_fs: float = 40.0,
    ):
        self.side = side
        self.phase_bins = phase_bins
        self.min_beats_for_template = min_beats_for_template
        self.max_beats_in_ensemble = max_beats_in_ensemble
        self.nominal_fs = nominal_fs

        # Fixed uniform cardiac phase axis: 0.0 to 1.0
        self._phase_grid = np.linspace(
            0.0, 1.0, self.phase_bins, endpoint=False
        )

        # Rolling raw buffer: tuples of (t, v)
        self._time_buffer: List[float] = []
        self._val_buffer: List[float] = []
        self._buffer_max_seconds = 20.0

        # Detected beat onsets: list of (t_onset, v_onset, buffer_idx)
        self._detected_onsets: List[Tuple[float, float, int]] = []

        # Rolling matrix of normalized beat templates
        self._beat_templates: List[np.ndarray] = []
        self._beat_rr_intervals: List[float] = []

        # Last snapshot
        self._last_snapshot: Optional[PulseAnalysis] = None

    def reset(self) -> None:
        """Clear all buffers and reset analysis state."""
        self._time_buffer.clear()
        self._val_buffer.clear()
        self._detected_onsets.clear()
        self._beat_templates.clear()
        self._beat_rr_intervals.clear()
        self._last_snapshot = None

    def append_sample(self, t: float, v: float) -> Optional[PulseAnalysis]:
        """Append a single sample (t, v) and recompute pulse snapshot."""
        if not math.isfinite(t) or not math.isfinite(v):
            return self._last_snapshot

        self._time_buffer.append(float(t))
        self._val_buffer.append(float(v))

        # Trim buffer to max window
        t_cutoff = t - self._buffer_max_seconds
        while len(self._time_buffer) > 40 and self._time_buffer[0] < t_cutoff:
            self._time_buffer.pop(0)
            self._val_buffer.pop(0)

        return self.compute()

    def feed_batch(
        self, times: np.ndarray, values: np.ndarray
    ) -> Optional[PulseAnalysis]:
        """Feed a contiguous batch of (t, v) samples."""
        valid = np.isfinite(times) & np.isfinite(values)
        if not np.any(valid):
            return self._last_snapshot

        for t, v in zip(times[valid], values[valid]):
            self._time_buffer.append(float(t))
            self._val_buffer.append(float(v))

        # Trim
        if self._time_buffer:
            t_cutoff = self._time_buffer[-1] - self._buffer_max_seconds
            while (
                len(self._time_buffer) > 40
                and self._time_buffer[0] < t_cutoff
            ):
                self._time_buffer.pop(0)
                self._val_buffer.pop(0)

        return self.compute()

    def compute(self) -> PulseAnalysis:
        """Analyze the current buffer and build a PulseAnalysis snapshot."""
        n_samples = len(self._val_buffer)
        if n_samples < 25:
            # Insufficient samples for cardiac analysis (< 0.6s @ 40Hz)
            snap = PulseAnalysis(
                side=self.side,
                phase=self._phase_grid.copy(),
                template=np.zeros(self.phase_bins),
                env_min=np.zeros(self.phase_bins),
                env_max=np.zeros(self.phase_bins),
                env_p25=np.zeros(self.phase_bins),
                env_p75=np.zeros(self.phase_bins),
                live_phase=np.zeros(0),
                live_value=np.zeros(0),
                features=PulseFeatures(),
                beat_count=0,
            )
            self._last_snapshot = snap
            return snap

        t_arr = np.array(self._time_buffer, dtype=np.float64)
        v_arr = np.array(self._val_buffer, dtype=np.float64)

        # Early check: flatline / constant signal has zero beats
        if float(np.std(v_arr)) < 1e-4:
            if len(v_arr) >= self.phase_bins:
                flat_tmpl = v_arr[-self.phase_bins:]
            else:
                flat_tmpl = np.full(self.phase_bins, float(v_arr[-1]))
            snap = PulseAnalysis(
                side=self.side,
                phase=self._phase_grid.copy(),
                template=flat_tmpl,
                env_min=np.zeros(self.phase_bins),
                env_max=np.zeros(self.phase_bins),
                env_p25=np.zeros(self.phase_bins),
                env_p75=np.zeros(self.phase_bins),
                live_phase=np.zeros(0),
                live_value=np.zeros(0),
                features=PulseFeatures(beat_count=0, reliable=False),
                beat_count=0,
            )
            self._last_snapshot = snap
            return snap

        # Estimate sampling rate
        dt = np.median(np.diff(t_arr))
        fs = 1.0 / dt if dt > 0 else self.nominal_fs

        # 1. Smooth waveform with Hanning window (~250ms)
        kernel_size = max(5, int(round(fs * 0.25)))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = np.hanning(kernel_size)
        kernel_sum = np.sum(kernel)
        if kernel_sum > 0:
            kernel /= kernel_sum
            v_smooth = np.convolve(v_arr, kernel, mode="same")
        else:
            v_smooth = v_arr.copy()

        # 2. First derivative for slope detection
        dv = np.gradient(v_smooth, t_arr)

        # 3. Detect cardiac onsets (valleys before systolic upstroke)
        # Minimum refractory period: ~0.38s (corresponds to max ~158 BPM)
        min_distance_samples = max(6, int(0.38 * fs))
        valleys = []
        for i in range(1, len(dv) - 1):
            if dv[i - 1] <= 0 and dv[i] > 0:
                valleys.append(i)

        # Filter valleys by minimum distance
        filtered_valleys = []
        for idx in valleys:
            if (
                not filtered_valleys
                or (idx - filtered_valleys[-1]) >= min_distance_samples
            ):
                filtered_valleys.append(idx)

        # 4. Extract individual beats, measure onset DC, resample to phase grid
        beat_templates = []
        rr_intervals = []
        onset_vals = []
        for b_idx in range(len(filtered_valleys) - 1):
            i_start = filtered_valleys[b_idx]
            i_end = filtered_valleys[b_idx + 1]
            t_beat = t_arr[i_start:i_end + 1]
            v_beat = v_arr[i_start:i_end + 1]
            rr = t_beat[-1] - t_beat[0]

            # Physiological RR bounds (0.28s to 2.0s <=> 30 to 214 BPM)
            if 0.28 <= rr <= 2.0 and len(t_beat) >= 4:
                # Normalize time to phase [0.0, 1.0]
                phase_beat = (t_beat - t_beat[0]) / rr
                resampled_v = np.interp(self._phase_grid, phase_beat, v_beat)
                beat_templates.append(resampled_v)
                rr_intervals.append(rr)
                onset_vals.append(float(v_beat[0]))

        # Keep rolling ensemble (last max_beats_in_ensemble)
        if len(beat_templates) > self.max_beats_in_ensemble:
            beat_templates = beat_templates[-self.max_beats_in_ensemble:]
            rr_intervals = rr_intervals[-self.max_beats_in_ensemble:]
            onset_vals = onset_vals[-self.max_beats_in_ensemble:]

        beat_count = len(beat_templates)

        # Baseline alignment: align beats to median onset to suppress
        # slow macro-drift while preserving true morphology variation
        if beat_count >= self.min_beats_for_template:
            med_onset = float(np.median(onset_vals)) if onset_vals else 0.0
            aligned_templates = [
                b - (o - med_onset)
                for b, o in zip(beat_templates, onset_vals)
            ]
        else:
            aligned_templates = beat_templates

        # 5. Live sweeping beat in progress
        live_phase = np.zeros(0, dtype=np.float64)
        live_value = np.zeros(0, dtype=np.float64)
        if filtered_valleys:
            last_onset_idx = filtered_valleys[-1]
            last_t = t_arr[last_onset_idx]
            if rr_intervals:
                curr_rr = float(np.median(rr_intervals))
            else:
                curr_rr = 60.0 / 75.0
            if curr_rr > 0:
                in_prog_t = t_arr[last_onset_idx:]
                in_prog_v = v_arr[last_onset_idx:]
                in_prog_phase = (in_prog_t - last_t) / curr_rr
                valid_sweep = in_prog_phase <= 1.05
                live_phase = in_prog_phase[valid_sweep]
                live_value = in_prog_v[valid_sweep]

        # 6. Ensemble statistics & features
        if beat_count >= self.min_beats_for_template:
            beats_matrix = np.array(aligned_templates, dtype=np.float64)
            template = np.median(beats_matrix, axis=0)
            env_min = np.min(beats_matrix, axis=0)
            env_max = np.max(beats_matrix, axis=0)
            env_p25 = np.percentile(beats_matrix, 25, axis=0)
            env_p75 = np.percentile(beats_matrix, 75, axis=0)

            features = self._calculate_features(
                template, beats_matrix, rr_intervals
            )
        else:
            template = np.zeros(self.phase_bins)
            env_min = np.zeros(self.phase_bins)
            env_max = np.zeros(self.phase_bins)
            env_p25 = np.zeros(self.phase_bins)
            env_p75 = np.zeros(self.phase_bins)
            features = PulseFeatures(beat_count=beat_count, reliable=False)

        snap = PulseAnalysis(
            side=self.side,
            phase=self._phase_grid.copy(),
            template=template,
            env_min=env_min,
            env_max=env_max,
            env_p25=env_p25,
            env_p75=env_p75,
            live_phase=live_phase,
            live_value=live_value,
            features=features,
            beat_count=beat_count,
        )
        self._last_snapshot = snap
        return snap

    def _calculate_features(
        self,
        template: np.ndarray,
        beats_matrix: np.ndarray,
        rr_intervals: List[float],
    ) -> PulseFeatures:
        """Calculate morphology features on the ensemble template."""
        median_rr = float(np.median(rr_intervals))
        hr_bpm = 60.0 / median_rr if median_rr > 0 else float("nan")

        t_min = float(np.min(template))
        t_max = float(np.max(template))
        t_mean = float(np.mean(template))
        amp = t_max - t_min

        # Gosling Pulsatility Index: (Peak - Nadir) / Mean
        pi = (amp / t_mean) if (t_mean > 1e-4 and amp > 0) else float("nan")

        # Pourcelot Resistivity Index: (Peak - Nadir) / Peak
        ri = (amp / t_max) if (t_max > 1e-4 and amp > 0) else float("nan")

        # Area under curve (normalized waveform trapezoid integral)
        if amp > 1e-4:
            norm_template = (template - t_min) / amp
            trap_fn = getattr(np, "trapezoid", getattr(np, "trapz", None))
            if trap_fn:
                auc = float(trap_fn(norm_template, self._phase_grid))
            else:
                auc = float("nan")
        else:
            auc = float("nan")

        # Systolic rise time (ms from onset to systolic peak)
        peak_idx = int(np.argmax(template))
        peak_phase = float(self._phase_grid[peak_idx])
        rise_time_ms = float(peak_phase * median_rr * 1000.0)

        # Augmentation Index and dicrotic shoulder detection
        aix, shoulder_idx = self._calculate_aix_and_shoulder(
            template, peak_idx, amp
        )
        shoulder_phase = (
            float(self._phase_grid[shoulder_idx])
            if shoulder_idx is not None
            else float("nan")
        )

        # Consistency: mean pairwise correlation between beats and template
        consistencies = []
        for beat in beats_matrix:
            r = compute_pearson_r(beat, template)
            if math.isfinite(r):
                consistencies.append(r)
        consistency = (
            float(np.mean(consistencies)) if consistencies else float("nan")
        )

        # Periodicity: 1.0 - clamped coefficient of variation of RR intervals
        if len(rr_intervals) >= 2:
            rr_mean = float(np.mean(rr_intervals))
            rr_std = float(np.std(rr_intervals))
            cv = rr_std / rr_mean if rr_mean > 0 else 1.0
            periodicity = float(max(0.0, 1.0 - cv))
        else:
            periodicity = float("nan")

        # Signal Quality Index (0 - 100%)
        if math.isfinite(consistency) and math.isfinite(periodicity):
            amp_score = min(1.0, max(0.0, amp / 0.15))
            sqi_raw = 100.0 * (
                0.45 * max(0.0, consistency)
                + 0.35 * max(0.0, periodicity)
                + 0.20 * amp_score
            )
            sqi = int(round(np.clip(sqi_raw, 0, 100)))
        else:
            sqi = 0

        # Reliability gate: regular physiological rhythm, valid HR, amp
        reliable = bool(
            len(rr_intervals) >= self.min_beats_for_template
            and (35.0 <= hr_bpm <= 210.0)
            and (amp >= 0.04)
            and (not math.isnan(consistency) and consistency >= 0.65)
        )

        period_rnd = (
            round(periodicity, 3)
            if math.isfinite(periodicity)
            else float("nan")
        )
        consist_rnd = (
            round(consistency, 3)
            if math.isfinite(consistency)
            else float("nan")
        )

        return PulseFeatures(
            hr_bpm=round(hr_bpm, 1),
            amp=round(amp, 3),
            pi=round(pi, 3),
            ri=round(ri, 3),
            auc=round(auc, 3),
            rise_time_ms=round(rise_time_ms, 1),
            aix=round(aix, 3) if math.isfinite(aix) else float("nan"),
            beat_count=len(beats_matrix),
            periodicity=period_rnd,
            consistency=consist_rnd,
            sqi=sqi,
            peak_phase=round(peak_phase, 3),
            shoulder_phase=(
                round(shoulder_phase, 3)
                if math.isfinite(shoulder_phase)
                else float("nan")
            ),
            reliable=reliable,
        )

    def _calculate_aix_and_shoulder(
        self, template: np.ndarray, peak_idx: int, amp: float
    ) -> Tuple[float, Optional[int]]:
        """Estimate Augmentation Index and locate dicrotic shoulder index."""
        if amp <= 1e-4 or peak_idx >= len(template) - 3:
            return float("nan"), None

        # Second derivative after the systolic peak to find dicrotic shoulder
        post_systolic = template[peak_idx:]
        if len(post_systolic) < 5:
            return float("nan"), None

        d2 = np.gradient(np.gradient(post_systolic))
        zero_crossings = np.where(np.diff(np.signbit(d2)))[0]
        if len(zero_crossings) > 0:
            shoulder_idx = peak_idx + zero_crossings[0]
            p2 = float(template[shoulder_idx])
            p1 = float(template[peak_idx])
            return float((p2 - p1) / amp), int(shoulder_idx)

        return float("nan"), None
