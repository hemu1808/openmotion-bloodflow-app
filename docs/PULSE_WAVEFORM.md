# Real-Time Cardiac Pulse-Waveform & Hemispheric Asymmetry Analysis

**Module:** `processing/pulse_analyzer.py`, `pulse_view.py`, `components/PulseView.qml`  
**Tracking Issues:** Issue #325, Epic #481  
**Target Branch:** `next`  
**Active Development Branch:** `Hemanth/Waveform`  
**Compliance:** Enterprise / Research Build Feature (gated out of Clinical builds)

---

## 1. Executive Summary

Optical blood flow index (BFI) captured by high-speed speckle contrast and laser interferometry sensors exhibits cardiac pulsatility. Each ventricular ejection generates a hemodynamic wave propagating through the cerebral vasculature.

The **Pulse-Waveform and Hemispheric Asymmetry Analyzer** provides real-time extraction, phase normalization, baseline detrending, rolling ensemble averaging, cardiovascular morphology statistics, and bilateral hemispheric asymmetry scoring across left and right cerebral hemispheres.

The feature operates autonomously across:
- **Live Acquisitions**: Real-time streaming from active sensor modules via `_LivePlotSink` and the pipeline `PulseSink`.
- **Database Replay**: Historical scan review via `PastScanSource`.
- **Sample Scan Replay**: Built-in `resources/sample_scan.csv` offline evaluation without hardware.

---

## 2. Mathematical Formulations & Algorithms

### 2.1 Cardiac Beat Onset Detection
Given a 1D continuous blood flow index stream $v(t)$, the algorithm extracts cardiac cycles using zero-crossing detection on the first derivative following adaptive smoothing:

1. **Adaptive Hanning Smoothing:**
   $$\bar{v}(t) = v(t) * w(t), \quad w(n) = 0.5 - 0.5 \cos\left(\frac{2\pi n}{N-1}\right)$$
   Where kernel width $N = \text{round}(0.25 \times f_s)$ suppresses high-frequency speckle noise without attenuating systolic peaks.

2. **Derivative Zero-Crossing:**
   $$\Delta v[i] = \frac{v[i+1] - v[i-1]}{t[i+1] - t[i-1]}$$
   Candidate beat onsets are identified at local minima where $\Delta v[i-1] \le 0$ and $\Delta v[i] > 0$.

3. **Refractory Period Gate:**
   Valleys within a physiological refractory period $\Delta t_{\text{refractory}} < 0.38\,\text{s}$ (corresponding to maximal physiological rate $> 158\,\text{BPM}$) are rejected to prevent false triggering on dicrotic notches.

### 2.2 Uniform Phase Normalization & Baseline Alignment
Each detected beat interval $[t_{\text{start}}, t_{\text{end}}]$ with duration $RR = t_{\text{end}} - t_{\text{start}}$ is mapped onto a normalized cardiac phase axis:
$$\phi(t) = \frac{t - t_{\text{start}}}{RR}, \quad \phi \in [0.0, 1.0)$$
The waveform is interpolated via linear spline onto a fixed grid of $M = 60$ phase bins:
$$v_{\text{beat}}[k] = \text{interp}\left(\phi_k, \phi(t), v(t)\right), \quad k \in \{0, 1, \dots, M-1\}$$

**Onset Baseline Detrending:**
To prevent slow macro baseline drift (e.g., Mayer waves or vasomotor changes) from artificially broadening the ensemble envelopes, each beat $v_{\text{beat}, j}$ is anchored to the median onset level:
$$v_{\text{beat}, j}^{\text{aligned}}(\phi) = v_{\text{beat}, j}(\phi) - \left(v_{\text{beat}, j}(0) - \text{median}(\{v_{\text{beat}, m}(0)\})\right)$$

### 2.3 Rolling Ensemble Averaging & Confidence Bands
For each side (Left and Right), an ensemble matrix of the last $K$ beats ($K \le 10$) is maintained:
$$\mathbf{B} = \begin{bmatrix} v_1^{\text{aligned}}(\phi) \\ v_2^{\text{aligned}}(\phi) \\ \vdots \\ v_K^{\text{aligned}}(\phi) \end{bmatrix}_{K \times M}$$

Statistical curves computed across columns:
- **Ensemble Template:** $T(\phi) = \text{median}_{j \in [1, K]}(B_{j, \phi})$
- **Full Envelopes:** $E_{\min}(\phi) = \min_j(B_{j, \phi})$, $E_{\max}(\phi) = \max_j(B_{j, \phi})$
- **Interquartile Range (IQR):** $E_{p25}(\phi) = P_{25}(B_{j, \phi})$, $E_{p75}(\phi) = P_{75}(B_{j, \phi})$

### 2.4 Morphology Metrics & Fiducial Detection
From the ensemble template $T(\phi)$ and RR intervals:
1. **Heart Rate (HR):**
   $$\text{HR} = \frac{60}{\text{median}(RR)}\,[\text{BPM}]$$
2. **Pulse Amplitude:**
   $$\text{Amp} = \max(T) - \min(T)$$
3. **Gosling Pulsatility Index (PI):**
   $$\text{PI} = \frac{\max(T) - \min(T)}{\text{mean}(T)}$$
4. **Pourcelot Resistivity Index (RI):**
   $$\text{RI} = \frac{\max(T) - \min(T)}{\max(T)}$$
5. **Area Under Curve (AUC):**
   $$\text{AUC} = \int_0^1 \frac{T(\phi) - \min(T)}{\max(T) - \min(T)} \, d\phi$$
6. **Systolic Rise Time & Peak ($P_1$):**
   $$t_{\text{rise}} = \phi_{\text{peak}} \times \text{median}(RR) \times 1000\,[\text{ms}]$$
   Located at $\phi_{\text{peak}} = \arg\max_\phi T(\phi)$.
7. **Augmentation Index (AIx) & Dicrotic Shoulder ($P_2$):**
   $$\text{AIx} = \frac{T(\phi_{\text{shoulder}}) - T(\phi_{\text{peak}})}{\text{Amp}}$$
   Where $\phi_{\text{shoulder}}$ is located via second derivative zero-crossings ($\frac{d^2 T}{d\phi^2} = 0$) on the systolic downslope.
8. **Signal Quality Index (SQI %):**
   $$\text{SQI} = \text{round}\left(100 \times \left(0.45 \cdot \text{Consistency} + 0.35 \cdot \text{Periodicity} + 0.20 \cdot \min\left(1, \frac{\text{Amp}}{0.15}\right)\right)\right)$$
9. **Periodicity:**
   $$\text{Periodicity} = \max\left(0, 1 - \frac{\sigma_{RR}}{\mu_{RR}}\right)$$
10. **Template Consistency:**
    $$\text{Consistency} = \frac{1}{K}\sum_{j=1}^K r\left(B_j, T\right)$$

### 2.5 Bilateral Hemispheric Asymmetry
Cross-hemispheric shape correlation between Left template $T_L$ and Right template $T_R$:
$$r_{LR} = \frac{\sum_{k=0}^{M-1} (T_L[k] - \bar{T}_L)(T_R[k] - \bar{T}_R)}{\sqrt{\sum_{k=0}^{M-1} (T_L[k] - \bar{T}_L)^2}\sqrt{\sum_{k=0}^{M-1} (T_R[k] - \bar{T}_R)^2}}$$

Clinical Asymmetry Categorization:
- **$r \ge 0.90$**: Symmetric
- **$0.75 \le r < 0.90$**: Mild Asymmetry
- **$r < 0.75$**: Significant Asymmetry

Metric deltas quantify hemodynamic divergence:
$$\Delta\text{HR} = \text{HR}_L - \text{HR}_R, \quad \Delta\text{Amp} = \text{Amp}_L - \text{Amp}_R, \quad \Delta\text{PI} = \text{PI}_L - \text{PI}_R$$

### 2.6 Physiological Reliability Gate
A template is flagged `reliable: true` only if:
- Beat count $K \ge 3$
- Heart Rate within physiological bounds: $35 \le \text{HR} \le 210\,\text{BPM}$
- Pulse Amplitude $\ge 0.04$
- Beat Consistency $r \ge 0.65$

---

## 3. UI Features & Enterprise Capabilities

- **In-Header Quick Switcher**: Segmented toggle `[ Plots | Pulse View ]` on the main viewer allows instant switching without opening modal dialogs.
- **Copy Metrics to Clipboard**: One-click export button formats complete morphology statistics into TSV/CSV format with instantaneous visual feedback.
- **Interactive Morphology Tooltips**: Hovering over any metric in `PulseStatsPanel.qml` reveals clinical formulas and diagnostic interpretations.
- **Fiducial Markers on Canvas**: Renders systolic peak ($P_1$) and dicrotic shoulder ($P_2$) directly on the template line.
- **Live Wavefront Sweeping**: Renders the in-progress cardiac beat with an accent leading dot and soft glow.

---

## 4. Clinical vs. Research Separation

In accordance with regulatory partitioning:
1. **PyInstaller (`openwater.spec`):**
   - Clinical builds exclude `pulse_view` and `processing.pulse_analyzer`.
   - Clinical QML bundle excludes `PulseView.qml`, `PulseCanvas.qml`, and `PulseStatsPanel.qml`.
2. **Nuitka Compilation (`scripts/build_nuitka.ps1`):**
   - `--nofollow-import-to=pulse_view`
   - `--nofollow-import-to=processing.pulse_analyzer`
   - Exclusion of pulse QML components in `--noinclude-data-files`.
3. **Runtime Connector Gate (`motion_connector.py`):**
   ```python
   if not _CLINICAL_BUILD and not bool(cfg.get("clinicalMode", False)):
       from pulse_view import PulseViewManager
       self._pulse_manager = PulseViewManager(emit_fn=self._emit_pulse_snapshot)
   ```

---

## 5. Verification & Testing

- **21 unit tests** in `tests/test_pulse_analyzer.py` and `tests/test_pulse_view.py`:
  - Synthetic signal pulse generation across heart rates (50–140 BPM).
  - Baseline detrending and SQI bounds verification.
  - Edge cases: flatline, NaN inputs, constant DC offset, insufficient beats.
  - Envelopes (min/max, p25/p75) and live sweeping trace validation.
  - Real hemodynamic data verification against `resources/sample_scan.csv`.
