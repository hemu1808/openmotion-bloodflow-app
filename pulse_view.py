"""Pulse-view controller and pipeline sink for pulse-waveform analysis.

Kept out of ``motion_connector.py`` (~4,700 lines) — the connector owns an
instance of ``PulseViewManager`` and forwards its output to QML via the
``pulseSnapshot(side, payload)`` signal.

Architectural pieces:
* ``PulseSink`` — pipeline sink for SDK-level `"pulse"` channel (if emitted).
* ``PulseViewManager`` — real-time orchestrator that consumes BFI streams from
  ``LiveScanSource`` or ``PastScanSource``, runs ``PulseWaveformAnalyzer`` per
  side, and emits throttled snapshots to QML.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Callable, Dict, Optional

import numpy as np

from processing.pulse_analyzer import (
    PulseWaveformAnalyzer,
    compute_pearson_r,
)

logger = logging.getLogger("openmotion.bloodflow-app.pulse_view")


class PulseSink:
    """Pipeline sink for SDK ``"pulse"`` channel -> ``emit_fn(side, val)``."""

    channels = {"pulse"}

    def __init__(self, emit_fn: Callable[[str, object], None]):
        self._emit = emit_fn

    def on_scan_start(self, meta) -> None:
        """Pipeline lifecycle hook."""
        pass

    def consume(self, channel: str, payload) -> None:
        if channel == "pulse" and payload is not None:
            side = getattr(payload, "side", None)
            if side in ("left", "right"):
                # If payload has to_dict / to_qvariant, use it; else dict
                val = (
                    payload.to_dict()
                    if hasattr(payload, "to_dict")
                    else payload
                )
                self._emit(side, val)

    def on_complete(self) -> None:
        """Pipeline lifecycle hook."""
        pass


class PulseViewManager:
    """Orchestrates pulse waveform analysis for left and right sensor modules.

    Consumes raw or side-averaged BFI samples, updates the per-side
    ``PulseWaveformAnalyzer``, and emits throttled QVariant-compatible
    snapshots for QML visualization.
    """

    def __init__(
        self,
        emit_fn: Callable[[str, Dict[str, object]], None],
        throttle_interval_sec: float = 0.08,  # ~12.5 Hz UI update rate
    ):
        self._emit = emit_fn
        self._throttle_interval_sec = throttle_interval_sec

        self._left_analyzer = PulseWaveformAnalyzer(side="left")
        self._right_analyzer = PulseWaveformAnalyzer(side="right")

        self._last_emit_time_left = 0.0
        self._last_emit_time_right = 0.0

        self._is_active = False

    @property
    def is_active(self) -> bool:
        return self._is_active

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self._is_active = bool(value)

    def reset(self) -> None:
        """Reset analyzers on scan boundaries."""
        self._left_analyzer.reset()
        self._right_analyzer.reset()
        self._last_emit_time_left = 0.0
        self._last_emit_time_right = 0.0

    def re_emit_snapshots(self) -> None:
        """Re-emit latest snapshots for QML subscribers upon view switch."""
        if self._left_analyzer._last_snapshot is not None:
            self._emit("left", self._left_analyzer._last_snapshot.to_dict())
        if self._right_analyzer._last_snapshot is not None:
            self._emit("right", self._right_analyzer._last_snapshot.to_dict())

    def ingest_sample(
        self, side: str, t: float, v: float, force: bool = False
    ) -> Optional[Dict[str, object]]:
        """Feed a single BFI sample for a side and optionally emit snapshot."""
        if side == "left":
            analyzer = self._left_analyzer
            last_emit = self._last_emit_time_left
        elif side == "right":
            analyzer = self._right_analyzer
            last_emit = self._last_emit_time_right
        else:
            return None

        snap = analyzer.append_sample(t, v)
        if snap is None:
            return None

        now = time.monotonic()
        if force or (now - last_emit) >= self._throttle_interval_sec:
            snap_dict = snap.to_dict()
            self._emit(side, snap_dict)
            if side == "left":
                self._last_emit_time_left = now
            else:
                self._last_emit_time_right = now
            return snap_dict

        return None

    def ingest_batch(
        self,
        side: str,
        times: np.ndarray,
        values: np.ndarray,
        force_emit: bool = True,
    ) -> Optional[Dict[str, object]]:
        """Feed a batch of BFI samples (used during replay/initialization)."""
        if side == "left":
            analyzer = self._left_analyzer
        elif side == "right":
            analyzer = self._right_analyzer
        else:
            return None

        snap = analyzer.feed_batch(times, values)
        if snap is None:
            return None

        snap_dict = snap.to_dict()
        if force_emit:
            self._emit(side, snap_dict)
            now = time.monotonic()
            if side == "left":
                self._last_emit_time_left = now
            else:
                self._last_emit_time_right = now

        return snap_dict

    def compute_asymmetry(self) -> Dict[str, object]:
        """Compute bilateral left vs right similarity and metric deltas."""
        left_snap = self._left_analyzer._last_snapshot
        right_snap = self._right_analyzer._last_snapshot

        if (
            left_snap is None
            or right_snap is None
            or left_snap.beat_count == 0
            or right_snap.beat_count == 0
        ):
            return {
                "shape_similarity": None,
                "hr_delta": None,
                "amp_delta": None,
                "pi_delta": None,
                "ri_delta": None,
            }

        r_val = compute_pearson_r(left_snap.template, right_snap.template)
        lf = left_snap.features
        rf = right_snap.features

        def _d(v1, v2):
            if math.isfinite(v1) and math.isfinite(v2):
                return v1 - v2
            return None

        sim_val = round(r_val, 3) if math.isfinite(r_val) else None
        return {
            "shape_similarity": sim_val,
            "hr_delta": _d(lf.hr_bpm, rf.hr_bpm),
            "amp_delta": _d(lf.amp, rf.amp),
            "pi_delta": _d(lf.pi, rf.pi),
            "ri_delta": _d(lf.ri, rf.ri),
        }
