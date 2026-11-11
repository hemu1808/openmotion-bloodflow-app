import QtQuick 6.0
import QtQuick.Controls 6.0
import QtQuick.Layouts 6.0
import OpenMotion 1.0

/*  PulseStatsPanel — left-vs-right pulse-shape comparison and asymmetry analysis.
 *
 *  Lays out a comprehensive morphology comparison table:
 *  one row per metric with Left | Right | Δ (L−R),
 *  with interactive tooltips explaining clinical formulas,
 *  plus bilateral shape-similarity (Pearson r) with asymmetry categorization.
 */
Rectangle {
    id: root

    property var leftSnap: null
    property var rightSnap: null

    color: AppTheme.bgCard
    radius: 10
    border.color: AppTheme.borderSoft
    border.width: 1

    implicitHeight: statsCol.implicitHeight + 24

    readonly property var _lf: (leftSnap && leftSnap.features) ? leftSnap.features : null
    readonly property var _rf: (rightSnap && rightSnap.features) ? rightSnap.features : null
    readonly property bool _lReliable: _lf && _lf.reliable === true
    readonly property bool _rReliable: _rf && _rf.reliable === true

    function _get(f, k) { return (f && f[k] !== undefined && f[k] !== null) ? f[k] : NaN }

    function _cell(f, reliable, k, d, gated) {
        if (gated && !reliable) return "—"
        var v = _get(f, k)
        return (v !== undefined && isFinite(v)) ? v.toFixed(d) : "—"
    }

    function _delta(k, d, gated) {
        if (gated && !(_lReliable && _rReliable)) return "—"
        var l = _get(_lf, k), r = _get(_rf, k)
        if (!isFinite(l) || !isFinite(r)) return "—"
        var dv = l - r
        return (dv >= 0 ? "+" : "") + dv.toFixed(d)
    }

    // [label, key, digits, unit, gated-on-reliability, tooltip]
    readonly property var _metrics: [
        ["Heart rate",          "hr_bpm",       0, "bpm", true,
         "Cardiac rate derived from median cardiac cycle (RR) interval."],
        ["Pulse amplitude",     "amp",          2, "BFI", true,
         "Systolic peak to diastolic nadir amplitude of the ensemble template."],
        ["Pulsatility index",   "pi",           2, "",    true,
         "Gosling Pulsatility Index = (Peak - Nadir) / Mean. Dynamic vascular impedance."],
        ["Resistivity index",   "ri",           2, "",    true,
         "Pourcelot Resistivity Index = (Peak - Nadir) / Peak. Cerebrovascular resistance."],
        ["Area under curve",    "auc",          2, "",    true,
         "Trapezoidal integral of the normalized ensemble template (0 to 1)."],
        ["Rise time",           "rise_time_ms", 0, "ms",  true,
         "Systolic upstroke duration: onset valley to systolic peak in ms."],
        ["Augmentation index",  "aix",          2, "",    true,
         "Augmentation Index (AIx) = (P2 - P1) / Amp. Arterial wave reflection marker."],
        ["Signal quality (SQI)","sqi",          0, "%",   false,
         "Composite Signal Quality Index: rhythm regularity, template consistency, and SNR."],
        ["Beats analysed",      "beat_count",   0, "",    false,
         "Number of detected cardiac beats accumulated in the rolling ensemble."],
        ["Signal periodicity",  "periodicity",  2, "",    false,
         "Rhythm regularity metric: 1.0 - CV(RR). Clamped between 0.0 and 1.0."],
        ["Template consistency","consistency",  2, "",    false,
         "Mean pairwise Pearson correlation r between individual beats and template."]
    ]

    function _pearson(a, b) {
        if (!a || !b || a.length === 0 || a.length !== b.length) return NaN
        var n = 0, sa = 0, sb = 0, i
        for (i = 0; i < a.length; i++) {
            if (isFinite(a[i]) && isFinite(b[i])) { sa += a[i]; sb += b[i]; n++ }
        }
        if (n < 2) return NaN
        var ma = sa / n, mb = sb / n, num = 0, da = 0, db = 0
        for (i = 0; i < a.length; i++) {
            if (isFinite(a[i]) && isFinite(b[i])) {
                var x = a[i] - ma, y = b[i] - mb
                num += x * y; da += x * x; db += y * y
            }
        }
        var den = Math.sqrt(da * db)
        return den > 0 ? num / den : NaN
    }

    readonly property real _shapeMatch:
        (leftSnap && rightSnap && leftSnap.beatCount > 0 && rightSnap.beatCount > 0)
        ? _pearson(leftSnap.template, rightSnap.template) : NaN

    readonly property string _asymLabel: {
        if (!isFinite(root._shapeMatch)) return "Evaluating..."
        if (root._shapeMatch >= 0.90) return "Symmetric"
        if (root._shapeMatch >= 0.75) return "Mild Asymmetry"
        return "Significant Asymmetry"
    }

    readonly property color _asymColor: {
        if (!isFinite(root._shapeMatch)) return AppTheme.textTertiary
        if (root._shapeMatch >= 0.90) return AppTheme.accentGreen
        if (root._shapeMatch >= 0.75) return AppTheme.accentYellow
        return AppTheme.accentRed
    }

    ColumnLayout {
        id: statsCol
        anchors.fill: parent
        anchors.margins: 12
        spacing: 3

        // ── Header Row ───────────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "Morphology & Asymmetry Analysis"
                color: AppTheme.textSecondary
                font.pixelSize: 13; font.bold: true
                Layout.preferredWidth: 220
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "Left"
                color: AppTheme.accentGreen
                font.pixelSize: 13; font.bold: true
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: 90
            }
            Text {
                text: "Right"
                color: AppTheme.accentBlue
                font.pixelSize: 13; font.bold: true
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: 90
            }
            Text {
                text: "Δ (L−R)"
                color: AppTheme.textTertiary
                font.pixelSize: 13; font.bold: true
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: 80
            }
        }

        Rectangle {
            Layout.fillWidth: true; height: 1
            color: AppTheme.borderSubtle; opacity: 0.5
        }

        // ── Pulse Detected Status ────────────────────────────────────────
        component DetectBadge: Text {
            property bool ok: false
            property bool has: false
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: 90
            font.pixelSize: 13; font.bold: true
            text: !has ? "—" : (ok ? "Reliable" : "Acquiring")
            color: !has ? AppTheme.textTertiary
                        : (ok ? AppTheme.accentGreen : AppTheme.accentYellow)
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "Rhythm gate status"
                color: AppTheme.textSecondary
                font.pixelSize: 12; font.bold: true
                Layout.preferredWidth: 220
            }
            Item { Layout.fillWidth: true }
            DetectBadge { has: root._lf !== null; ok: root._lReliable }
            DetectBadge { has: root._rf !== null; ok: root._rReliable }
            Item { Layout.preferredWidth: 80 }
        }

        // ── Metrics Rows with Interactive Tooltip ────────────────────────
        Repeater {
            model: root._metrics
            delegate: RowLayout {
                id: mRow
                required property var modelData
                Layout.fillWidth: true
                spacing: 8

                MouseArea {
                    id: rowMa
                    Layout.preferredWidth: 220
                    Layout.preferredHeight: 18
                    hoverEnabled: true

                    ToolTip.visible: rowMa.containsMouse
                    ToolTip.text: mRow.modelData[5]
                    ToolTip.delay: 350

                    Text {
                        anchors.fill: parent
                        text: mRow.modelData[0] + (mRow.modelData[3] ? "  (" + mRow.modelData[3] + ")" : "")
                        color: rowMa.containsMouse ? AppTheme.textPrimary : AppTheme.textTertiary
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }

                Item { Layout.fillWidth: true }
                Text {
                    text: root._cell(root._lf, root._lReliable, mRow.modelData[1], mRow.modelData[2], mRow.modelData[4])
                    color: AppTheme.textPrimary; font.pixelSize: 13; font.family: "Roboto Mono"
                    horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 90
                }
                Text {
                    text: root._cell(root._rf, root._rReliable, mRow.modelData[1], mRow.modelData[2], mRow.modelData[4])
                    color: AppTheme.textPrimary; font.pixelSize: 13; font.family: "Roboto Mono"
                    horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 90
                }
                Text {
                    text: root._delta(mRow.modelData[1], mRow.modelData[2], mRow.modelData[4])
                    color: AppTheme.textSecondary; font.pixelSize: 13; font.family: "Roboto Mono"
                    horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 80
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true; height: 1
            color: AppTheme.borderSubtle; opacity: 0.5
            Layout.topMargin: 4
        }

        // ── Bilateral Shape Similarity & Hemispheric Asymmetry ───────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "Bilateral Hemispheric Similarity"
                color: AppTheme.textPrimary; font.pixelSize: 13; font.bold: true
                Layout.preferredWidth: 240
            }
            Item { Layout.fillWidth: true }

            // Classification Pill
            Rectangle {
                Layout.preferredHeight: 22
                Layout.preferredWidth: asymTxt.implicitWidth + 16
                radius: 11
                color: Qt.rgba(root._asymColor.r, root._asymColor.g, root._asymColor.b, 0.16)
                border.color: root._asymColor; border.width: 1

                Text {
                    id: asymTxt
                    anchors.centerIn: parent
                    text: root._asymLabel
                    color: root._asymColor
                    font.pixelSize: 11; font.bold: true
                }
            }

            // Pearson r Readout
            Rectangle {
                Layout.preferredWidth: 110; Layout.preferredHeight: 22; radius: 11
                color: AppTheme.bgElevated
                border.color: AppTheme.borderSoft; border.width: 1
                Text {
                    anchors.centerIn: parent
                    text: isFinite(root._shapeMatch)
                          ? "r = " + root._shapeMatch.toFixed(3) : "r = —"
                    color: AppTheme.textPrimary; font.pixelSize: 13; font.bold: true; font.family: "Roboto Mono"
                }
            }
        }
    }
}
