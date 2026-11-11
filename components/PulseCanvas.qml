import QtQuick 6.0
import QtQuick.Layouts 6.0
import OpenMotion 1.0

/*  PulseCanvas — one side's cardiac pulse window.
 *
 *  Renders, back to front:
 *    1. subtle background grid + calibrated axis labels (Phase 0-100%, BFI),
 *    2. min/max envelope over recent beats (translucent background band),
 *    3. p25-p75 IQR band (stronger confidence interval fill),
 *    4. ensemble-median "template" pulse (bold accent line),
 *    5. systolic peak (P1) and dicrotic shoulder (P2) fiducial markers,
 *    6. live in-progress beat sweeping left -> right (bright trace + glowing dot).
 *
 *  `snap` is one side's PulseAnalysis dictionary: keys phase/template/
 *  envMin/envMax/envP25/envP75/livePhase/liveValue/features/beatCount.
 */
Item {
    id: root

    property var snap: null
    property string title: "LEFT"
    property color accent: AppTheme.accentGreen
    property real yMin: 0.0
    property real yMax: 10.0

    readonly property var _f: (snap && snap.features) ? snap.features : null
    readonly property bool _hasData: snap && snap.beatCount > 0
    readonly property bool _reliable: _f && _f.reliable === true

    onSnapChanged: canvas.requestPaint()
    onYMinChanged: canvas.requestPaint()
    onYMaxChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Rectangle {
        anchors.fill: parent
        radius: 10
        color: AppTheme.plotCellBg
        border.color: AppTheme.borderSoft
        border.width: 1
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        anchors.margins: 1
        renderStrategy: Canvas.Cooperative
        opacity: (root._hasData && !root._reliable) ? 0.35 : 1.0

        readonly property real padL: 46
        readonly property real padR: 16
        readonly property real padT: 38
        readonly property real padB: 30

        function _x(p) { return padL + p * (width - padL - padR) }
        function _y(v) {
            var span = (root.yMax - root.yMin) || 1
            var f = (v - root.yMin) / span
            return padT + (1 - f) * (height - padT - padB)
        }

        function _band(ctx, phase, lo, hi) {
            ctx.beginPath()
            var started = false
            for (var i = 0; i < phase.length; i++) {
                if (!isFinite(hi[i])) continue
                var x = _x(phase[i]), y = _y(hi[i])
                if (!started) { ctx.moveTo(x, y); started = true }
                else ctx.lineTo(x, y)
            }
            for (var j = phase.length - 1; j >= 0; j--) {
                if (!isFinite(lo[j])) continue
                ctx.lineTo(_x(phase[j]), _y(lo[j]))
            }
            ctx.closePath()
            ctx.fill()
        }

        function _line(ctx, phase, vals, from) {
            ctx.beginPath()
            var started = false
            for (var i = 0; i < phase.length; i++) {
                if (!isFinite(vals[i]) || phase[i] < from - 1e-9) continue
                var x = _x(phase[i]), y = _y(vals[i])
                if (!started) { ctx.moveTo(x, y); started = true }
                else ctx.lineTo(x, y)
            }
            ctx.stroke()
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)

            // ── background grid ──────────────────────────────────────────
            ctx.strokeStyle = AppTheme.plotGrid
            ctx.lineWidth = 1
            ctx.globalAlpha = 0.45
            for (var gy = 0; gy <= 4; gy++) {
                var y = padT + gy / 4 * (height - padT - padB)
                ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(width - padR, y); ctx.stroke()
            }
            for (var gx = 0; gx <= 4; gx++) {
                var x = padL + gx / 4 * (width - padL - padR)
                ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, height - padB); ctx.stroke()
            }
            ctx.globalAlpha = 1.0

            // ── axis labels ──────────────────────────────────────────────
            ctx.fillStyle = AppTheme.plotLabel
            ctx.font = "10px sans-serif"
            ctx.textAlign = "right"; ctx.textBaseline = "middle"
            for (var ly = 0; ly <= 4; ly++) {
                var val = root.yMax - ly / 4 * (root.yMax - root.yMin)
                ctx.fillText(val.toFixed(1), padL - 6, padT + ly / 4 * (height - padT - padB))
            }
            ctx.textAlign = "center"; ctx.textBaseline = "top"
            var labels = ["0%", "25%", "50%", "75%", "100%"]
            for (var lx = 0; lx <= 4; lx++) {
                ctx.fillText(labels[lx], padL + lx / 4 * (width - padL - padR), height - padB + 6)
            }

            if (!root._hasData) {
                ctx.fillStyle = AppTheme.textTertiary
                ctx.font = "14px sans-serif"
                ctx.textAlign = "center"; ctx.textBaseline = "middle"
                ctx.fillText("Waiting for pulse waveform…", (padL + width - padR) / 2, (padT + height - padB) / 2)
                return
            }

            var phase = snap.phase
            // ── 1. min/max envelope ───────────────────────────────────────
            ctx.fillStyle = root.accent
            ctx.globalAlpha = 0.12
            _band(ctx, phase, snap.envMin, snap.envMax)

            // ── 2. p25-p75 IQR confidence band ────────────────────────────
            ctx.globalAlpha = 0.22
            _band(ctx, phase, snap.envP25, snap.envP75)
            ctx.globalAlpha = 1.0

            // ── 3. ensemble median template ──────────────────────────────
            ctx.strokeStyle = root.accent
            ctx.lineWidth = 2.4
            _line(ctx, phase, snap.template, -1)

            // ── 4. fiducial markers (Systolic Peak P1, Dicrotic Shoulder P2)
            if (root._reliable && root._f && snap.template && snap.template.length > 0) {
                var pkP = root._f.peakPhase
                if (pkP !== undefined && pkP !== null && isFinite(pkP)) {
                    var pkIdx = Math.round(pkP * (phase.length - 1))
                    if (pkIdx >= 0 && pkIdx < snap.template.length) {
                        var px = _x(pkP), py = _y(snap.template[pkIdx])
                        ctx.fillStyle = root.accent
                        ctx.beginPath(); ctx.arc(px, py, 4.0, 0, 2 * Math.PI); ctx.fill()
                        ctx.font = "bold 9px sans-serif"
                        ctx.fillStyle = AppTheme.textPrimary
                        ctx.textAlign = "center"; ctx.textBaseline = "bottom"
                        ctx.fillText("P1", px, py - 6)
                    }
                }
                var shP = root._f.shoulderPhase
                if (shP !== undefined && shP !== null && isFinite(shP)) {
                    var shIdx = Math.round(shP * (phase.length - 1))
                    if (shIdx >= 0 && shIdx < snap.template.length) {
                        var sx = _x(shP), sy = _y(snap.template[shIdx])
                        ctx.fillStyle = AppTheme.textSecondary
                        ctx.beginPath(); ctx.arc(sx, sy, 3.2, 0, 2 * Math.PI); ctx.fill()
                        ctx.font = "9px sans-serif"
                        ctx.fillStyle = AppTheme.textTertiary
                        ctx.textAlign = "center"; ctx.textBaseline = "bottom"
                        ctx.fillText("P2", sx, sy - 5)
                    }
                }
            }

            // ── 5. live in-progress sweeping beat ─────────────────────────
            if (snap.livePhase && snap.livePhase.length > 1) {
                ctx.strokeStyle = AppTheme.textPrimary
                ctx.lineWidth = 1.6
                ctx.globalAlpha = 0.92
                _line(ctx, snap.livePhase, snap.liveValue, -1)
                ctx.globalAlpha = 1.0

                // Glowing leading dot at sweeping wavefront
                var k = snap.livePhase.length - 1
                if (isFinite(snap.liveValue[k])) {
                    var lxPos = _x(snap.livePhase[k])
                    var lyPos = _y(snap.liveValue[k])
                    // Outer glow
                    ctx.fillStyle = Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.35)
                    ctx.beginPath(); ctx.arc(lxPos, lyPos, 6.0, 0, 2 * Math.PI); ctx.fill()
                    // Core dot
                    ctx.fillStyle = root.accent
                    ctx.beginPath(); ctx.arc(lxPos, lyPos, 3.0, 0, 2 * Math.PI); ctx.fill()
                }
            }
        }
    }

    // ── title & telemetry header ─────────────────────────────────────
    RowLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 10
        spacing: 8

        Rectangle {
            width: 10; height: 10; radius: 5; color: root.accent
            Layout.alignment: Qt.AlignVCenter
        }
        Text {
            text: root.title
            color: AppTheme.textPrimary
            font.pixelSize: 15; font.bold: true
        }
        Item { Layout.fillWidth: true }

        // SQI Pill (Signal Quality Index)
        Rectangle {
            visible: root._hasData
            Layout.preferredHeight: 20
            Layout.preferredWidth: sqiTxt.implicitWidth + 14
            radius: 10
            readonly property int _q: (root._f && root._f.sqi !== undefined) ? root._f.sqi : 0
            readonly property color _qColor: _q >= 80 ? AppTheme.accentGreen
                                           : _q >= 60 ? AppTheme.accentYellow
                                           : AppTheme.accentRed
            color: Qt.rgba(_qColor.r, _qColor.g, _qColor.b, 0.18)
            border.color: _qColor; border.width: 1

            Text {
                id: sqiTxt
                anchors.centerIn: parent
                text: "SQI " + parent._q + "%"
                color: parent._qColor
                font.pixelSize: 11; font.bold: true; font.family: "Roboto Mono"
            }
        }

        // Heart Rate
        Text {
            visible: root._reliable
            text: (root._f && isFinite(root._f.hr_bpm))
                  ? Math.round(root._f.hr_bpm) + " bpm" : "-- bpm"
            color: AppTheme.textPrimary
            font.pixelSize: 15; font.bold: true; font.family: "Roboto Mono"
        }

        // Pulsatility Index
        Text {
            visible: root._reliable
            text: (root._f && isFinite(root._f.pi))
                  ? "PI " + root._f.pi.toFixed(2) : "PI --"
            color: AppTheme.textSecondary
            font.pixelSize: 13; font.family: "Roboto Mono"
        }

        Text {
            visible: root._hasData && !root._reliable
            text: "Acquiring..."
            color: AppTheme.accentYellow
            font.pixelSize: 13; font.bold: true
        }
    }

    // Centered "Acquiring pulse" banner when data exists but gate is not yet reliable
    Rectangle {
        visible: root._hasData && !root._reliable
        anchors.centerIn: parent
        width: noPulseLabel.width + 28; height: noPulseLabel.height + 16
        radius: 8
        color: Qt.rgba(AppTheme.accentYellow.r, AppTheme.accentYellow.g,
                       AppTheme.accentYellow.b, 0.14)
        border.color: AppTheme.accentYellow; border.width: 1
        Text {
            id: noPulseLabel
            anchors.centerIn: parent
            text: "Acquiring cardiac cycles (" + (root.snap ? root.snap.beatCount : 0) + " beats)..."
            color: AppTheme.accentYellow
            font.pixelSize: 14; font.bold: true
        }
    }
}
