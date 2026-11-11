import QtQuick 6.0
import QtQuick.Controls 6.0
import QtQuick.Layouts 6.0
import OpenMotion 1.0

/*  PulseView — enterprise-grade cardiac pulse-waveform viewer (Research mode).
 *
 *  Provides bilateral synchronized real-time pulse morphology analysis:
 *  - Left and Right pulse canvases with ensemble templates, IQR bounds,
 *    min/max envelopes, and live sweeping wavefronts.
 *  - Hemispheric asymmetry stats panel with clinical metrics and Pearson-r.
 *  - In-header quick toggle back to Time Series plots.
 *  - Export/copy metrics summary feature for researcher workflows.
 */
Item {
    id: root

    property bool active: false
    property bool scanning: false

    property var leftSnap: null
    property var rightSnap: null
    property real yMin: 0.0
    property real yMax: 10.0

    readonly property bool hasData: leftSnap !== null || rightSnap !== null

    onActiveChanged: if (active) {
        MotionInterface.requestPulseSnapshot()
    }
    onScanningChanged: if (scanning) {
        root.leftSnap = null
        root.rightSnap = null
    }

    Component.onCompleted: if (active) {
        MotionInterface.requestPulseSnapshot()
    }

    function _extent(snap, ext) {
        if (!snap || snap.beatCount <= 0) return ext
        var arrs = [snap.envMin, snap.envMax, snap.liveValue]
        for (var a = 0; a < arrs.length; a++) {
            var arr = arrs[a]
            if (!arr) continue
            for (var i = 0; i < arr.length; i++) {
                if (isFinite(arr[i])) {
                    if (arr[i] < ext[0]) ext[0] = arr[i]
                    if (arr[i] > ext[1]) ext[1] = arr[i]
                }
            }
        }
        return ext
    }

    function _recomputeScale() {
        var ext = _extent(rightSnap, _extent(leftSnap, [Infinity, -Infinity]))
        if (ext[0] === Infinity) { yMin = 0.0; yMax = 10.0; return }
        var pad = (ext[1] - ext[0]) * 0.14
        if (pad <= 0) pad = 0.5
        yMin = Math.max(0.0, ext[0] - pad)
        yMax = ext[1] + pad
    }

    Connections {
        target: MotionInterface
        function onPulseSnapshot(side, payload) {
            if (side === "left") root.leftSnap = payload
            else if (side === "right") root.rightSnap = payload
            root._recomputeScale()
        }
    }

    function copyMetricsSummary() {
        if (!leftSnap && !rightSnap) return
        var lf = leftSnap ? leftSnap.features : {}
        var rf = rightSnap ? rightSnap.features : {}
        var txt = "Metric\tLeft\tRight\n"
        var keys = [
            ["Heart Rate (bpm)", "hr_bpm"],
            ["Pulse Amplitude (BFI)", "amp"],
            ["Gosling Pulsatility Index (PI)", "pi"],
            ["Pourcelot Resistivity Index (RI)", "ri"],
            ["Area Under Curve (AUC)", "auc"],
            ["Rise Time (ms)", "rise_time_ms"],
            ["Augmentation Index (AIx)", "aix"],
            ["Signal Quality Index (%)", "sqi"],
            ["Beats Analysed", "beat_count"],
            ["Periodicity", "periodicity"],
            ["Consistency", "consistency"]
        ]
        for (var i = 0; i < keys.length; i++) {
            var label = keys[i][0], k = keys[i][1]
            var lv = (lf && lf[k] !== undefined && lf[k] !== null) ? lf[k] : "N/A"
            var rv = (rf && rf[k] !== undefined && rf[k] !== null) ? rf[k] : "N/A"
            txt += label + "\t" + lv + "\t" + rv + "\n"
        }
        MotionInterface.copyToClipboard(txt)
        copyFeedbackTimer.restart()
    }

    Rectangle {
        anchors.fill: parent
        color: AppTheme.bgPlot
        radius: 8
        border.color: AppTheme.borderSoft
        border.width: 1
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        // ── Top Header Toolbar ───────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Text {
                text: "Hemodynamic Pulse Waveforms"
                color: AppTheme.textPrimary
                font.pixelSize: 20; font.bold: true
            }

            // Acquisition Pill
            Rectangle {
                visible: root.scanning
                Layout.preferredHeight: 22
                Layout.preferredWidth: liveLbl.implicitWidth + 20
                radius: 11
                readonly property color _pillAccent:
                    MotionInterface.appConfig.demoMode === true
                    ? AppTheme.accentBlue : AppTheme.accentGreen
                color: Qt.rgba(_pillAccent.r, _pillAccent.g, _pillAccent.b, 0.20)
                border.color: _pillAccent; border.width: 1
                Text {
                    id: liveLbl
                    anchors.centerIn: parent
                    text: MotionInterface.appConfig.demoMode === true ? "DEMO REPLAY" : "LIVE CAPTURE"
                    color: parent._pillAccent
                    font.pixelSize: 11; font.bold: true
                }
            }

            Item { Layout.fillWidth: true }

            // Copy Metrics Button
            Button {
                visible: root.hasData
                Layout.preferredHeight: 28
                Layout.preferredWidth: copyLbl.implicitWidth + 24
                background: Rectangle {
                    radius: 6
                    color: copyFeedbackTimer.running ? AppTheme.accentGreen : AppTheme.bgInput
                    border.color: AppTheme.borderSubtle; border.width: 1
                }
                contentItem: Text {
                    id: copyLbl
                    text: copyFeedbackTimer.running ? "Copied!" : "Copy Metrics"
                    color: copyFeedbackTimer.running ? "#FFFFFF" : AppTheme.textPrimary
                    font.pixelSize: 12; font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: root.copyMetricsSummary()
            }

            Timer {
                id: copyFeedbackTimer
                interval: 1800
                repeat: false
            }

            // Mode Selector Pill (Instant toggle between Plots and Pulse View)
            Rectangle {
                Layout.preferredHeight: 30
                Layout.preferredWidth: modeRow.implicitWidth + 8
                radius: 6
                color: AppTheme.bgInput
                border.color: AppTheme.borderSubtle
                border.width: 1

                RowLayout {
                    id: modeRow
                    anchors.centerIn: parent
                    spacing: 4

                    Rectangle {
                        Layout.preferredHeight: 24
                        Layout.preferredWidth: 90
                        radius: 4
                        color: AppTheme.bgElevated
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: MotionInterface.setConfig("viewerMode", "default")
                        }
                        Text {
                            anchors.centerIn: parent
                            text: "Plots"
                            color: AppTheme.textSecondary
                            font.pixelSize: 12; font.bold: true
                        }
                    }

                    Rectangle {
                        Layout.preferredHeight: 24
                        Layout.preferredWidth: 90
                        radius: 4
                        color: AppTheme.accentInteractive
                        Text {
                            anchors.centerIn: parent
                            text: "Pulse View"
                            color: "#FFFFFF"
                            font.pixelSize: 12; font.bold: true
                        }
                    }
                }
            }
        }

        // ── Bilateral Pulse Canvases ─────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            PulseCanvas {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "LEFT HEMISPHERE"
                accent: AppTheme.accentGreen
                snap: root.leftSnap
                yMin: root.yMin
                yMax: root.yMax
            }

            PulseCanvas {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "RIGHT HEMISPHERE"
                accent: AppTheme.accentBlue
                snap: root.rightSnap
                yMin: root.yMin
                yMax: root.yMax
            }
        }

        // ── Bilateral Comparison Stats Panel ─────────────────────────────
        PulseStatsPanel {
            Layout.fillWidth: true
            leftSnap: root.leftSnap
            rightSnap: root.rightSnap
        }
    }

    // ── Placeholder overlay when idle / no data ──────────────────────────
    Rectangle {
        anchors.fill: parent
        visible: !root.hasData
        color: AppTheme.overlayBg

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 12

            Text {
                Layout.alignment: Qt.AlignHCenter
                color: AppTheme.textPrimary
                font.pixelSize: 17; font.bold: true
                text: root.scanning
                      ? "Acquiring cardiac cycles — extracting morphological template..."
                      : (MotionInterface.appConfig.demoMode === true
                         ? "Demo Replay Mode — click Start Capture to replay scan."
                         : "No scan data loaded — start a capture or load a historical recording.")
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                color: AppTheme.textSecondary
                font.pixelSize: 13
                text: "Processes continuous BFI streams to quantify arterial pulsatility and hemispheric asymmetry."
            }
        }
    }
}
