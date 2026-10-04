import QtQuick

Item {
    id: chart
    property var ui
    property var points: []
    property string mode: "line"  // line, bars, candles
    property string valueKey: "cumulative"
    property string emptyText: "暂无可用数据"
    property int maxPoints: mode === "candles" ? 72 : 90
    property int hoverIndex: -1
    property real hoverX: 0

    function valueOf(row, key) {
        if (!row || row[key] === undefined || row[key] === null || row[key] === "") return NaN
        const value = Number(row[key])
        return isFinite(value) ? value : NaN
    }

    function validRows() {
        if (!chart.points) return []
        const all = chart.points
        const rows = []
        const begin = Math.max(0, all.length - chart.maxPoints)
        for (let i = begin; i < all.length; i++) {
            const p = all[i]
            if (chart.mode === "candles") {
                if (isFinite(chart.valueOf(p, "open"))
                        && isFinite(chart.valueOf(p, "high"))
                        && isFinite(chart.valueOf(p, "low"))
                        && isFinite(chart.valueOf(p, "close"))) rows.push(p)
            } else if (isFinite(chart.valueOf(p, chart.valueKey))) rows.push(p)
        }
        return rows
    }

    function compact(value) {
        const magnitude = Math.abs(value)
        if (magnitude >= 1000) return (value / 1000).toFixed(1) + "k"
        if (magnitude >= 100) return value.toFixed(0)
        if (magnitude >= 10) return value.toFixed(1)
        return value.toFixed(2)
    }

    function hoverText() {
        const rows = chart.validRows()
        if (chart.hoverIndex < 0 || chart.hoverIndex >= rows.length) return ""
        const row = rows[chart.hoverIndex]
        const label = String(row.day || row.time || "")
        if (chart.mode === "candles")
            return label + "\n开 " + chart.valueOf(row, "open").toFixed(3)
                   + "  高 " + chart.valueOf(row, "high").toFixed(3)
                   + "  低 " + chart.valueOf(row, "low").toFixed(3)
                   + "  收 " + chart.valueOf(row, "close").toFixed(3)
        return label + "\n" + chart.valueOf(row, chart.valueKey).toFixed(2)
    }

    onPointsChanged: canvas.requestPaint()
    onModeChanged: canvas.requestPaint()
    onValueKeyChanged: canvas.requestPaint()
    onUiChanged: canvas.requestPaint()
    onHoverIndexChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            if (!chart.points || chart.points.length === 0 || width < 100 || height < 80) return

            const rows = chart.validRows()
            if (rows.length === 0) return

            const left = 10
            const top = 14
            const right = width - 55
            const bottom = height - 28
            const plotWidth = right - left
            const plotHeight = bottom - top
            let lowest = Number.POSITIVE_INFINITY
            let highest = Number.NEGATIVE_INFINITY
            for (let i = 0; i < rows.length; i++) {
                const p = rows[i]
                if (chart.mode === "candles") {
                    lowest = Math.min(lowest, chart.valueOf(p, "low"))
                    highest = Math.max(highest, chart.valueOf(p, "high"))
                } else {
                    const value = chart.valueOf(p, chart.valueKey)
                    lowest = Math.min(lowest, value)
                    highest = Math.max(highest, value)
                }
            }
            if (chart.mode === "bars") {
                lowest = Math.min(lowest, 0)
                highest = Math.max(highest, 0)
            }
            if (!isFinite(lowest) || !isFinite(highest)) return
            const padding = Math.max((highest - lowest) * 0.08, chart.mode === "candles" ? 0.2 : 1)
            lowest -= padding
            highest += padding
            const span = highest - lowest || 1
            const y = function(value) { return bottom - (value - lowest) / span * plotHeight }

            ctx.lineWidth = 1
            ctx.strokeStyle = String(chart.ui ? chart.ui.chartGrid : "#E3EAF2")
            ctx.fillStyle = String(chart.ui ? chart.ui.muted : "#60758D")
            ctx.font = "11px Microsoft YaHei UI"
            ctx.textAlign = "left"
            for (let tick = 0; tick < 4; tick++) {
                const value = lowest + span * tick / 3
                const py = y(value)
                ctx.beginPath()
                ctx.moveTo(left, py + 0.5)
                ctx.lineTo(right, py + 0.5)
                ctx.stroke()
                ctx.fillText(chart.compact(value), right + 7, py + 4)
            }

            if (chart.mode === "candles") {
                const step = plotWidth / rows.length
                const bodyWidth = Math.max(2, Math.min(10, step * 0.64))
                for (let i = 0; i < rows.length; i++) {
                    const p = rows[i]
                    const open = chart.valueOf(p, "open")
                    const close = chart.valueOf(p, "close")
                    const x = left + (i + 0.5) * step
                    ctx.strokeStyle = close >= open ? String(chart.ui.chartUp) : String(chart.ui.chartDown)
                    ctx.fillStyle = ctx.strokeStyle
                    ctx.beginPath()
                    ctx.moveTo(x, y(chart.valueOf(p, "high")))
                    ctx.lineTo(x, y(chart.valueOf(p, "low")))
                    ctx.stroke()
                    const upper = Math.min(y(open), y(close))
                    const bodyHeight = Math.max(2, Math.abs(y(open) - y(close)))
                    if (p.complete === false)
                        ctx.strokeRect(x - bodyWidth / 2, upper, bodyWidth, bodyHeight)
                    else
                        ctx.fillRect(x - bodyWidth / 2, upper, bodyWidth, bodyHeight)
                }
            } else if (chart.mode === "bars") {
                const step = plotWidth / rows.length
                const barWidth = Math.max(3, Math.min(20, step * 0.58))
                const baseline = y(0)
                for (let i = 0; i < rows.length; i++) {
                    const value = chart.valueOf(rows[i], chart.valueKey)
                    const py = y(value)
                    ctx.fillStyle = value >= 0 ? String(chart.ui.chartUp) : String(chart.ui.chartDown)
                    ctx.fillRect(left + (i + 0.5) * step - barWidth / 2,
                                 Math.min(py, baseline), barWidth, Math.max(1, Math.abs(baseline - py)))
                }
            } else {
                const x = function(index) {
                    return left + (rows.length === 1 ? 0 : index / (rows.length - 1) * plotWidth)
                }
                ctx.beginPath()
                for (let i = 0; i < rows.length; i++) {
                    const py = y(chart.valueOf(rows[i], chart.valueKey))
                    if (i === 0) ctx.moveTo(x(i), py)
                    else ctx.lineTo(x(i), py)
                }
                ctx.lineWidth = 2.3
                ctx.strokeStyle = String(chart.ui.chartBlue)
                ctx.stroke()
                ctx.lineTo(x(rows.length - 1), bottom)
                ctx.lineTo(x(0), bottom)
                ctx.closePath()
                ctx.globalAlpha = 0.09
                ctx.fillStyle = String(chart.ui.chartBlue)
                ctx.fill()
                ctx.globalAlpha = 1
            }

            if (chart.hoverIndex >= 0 && chart.hoverIndex < rows.length) {
                const step = plotWidth / rows.length
                const hoverPointX = chart.mode === "line"
                    ? left + (rows.length === 1 ? 0 : chart.hoverIndex / (rows.length - 1) * plotWidth)
                    : left + (chart.hoverIndex + 0.5) * step
                ctx.beginPath()
                ctx.moveTo(hoverPointX, top)
                ctx.lineTo(hoverPointX, bottom)
                ctx.strokeStyle = String(chart.ui ? chart.ui.muted : "#60758D")
                ctx.globalAlpha = 0.45
                ctx.lineWidth = 1
                ctx.stroke()
                ctx.globalAlpha = 1
            }

            ctx.fillStyle = String(chart.ui ? chart.ui.faint : "#8A9AAF")
            ctx.font = "11px Microsoft YaHei UI"
            ctx.textAlign = "left"
            const first = rows[0]
            const last = rows[rows.length - 1]
            const firstLabel = first.day || first.time || ""
            const lastLabel = last.day || last.time || ""
            ctx.fillText(String(firstLabel).slice(0, 16), left, height - 6)
            ctx.textAlign = "right"
            ctx.fillText(String(lastLabel).slice(0, 16), right, height - 6)
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onPositionChanged: function(mouse) {
            const rows = chart.validRows()
            const plotWidth = width - 65
            if (rows.length === 0 || plotWidth <= 0 || mouse.x < 10 || mouse.x > width - 55) {
                chart.hoverIndex = -1
                return
            }
            const ratio = (mouse.x - 10) / plotWidth
            chart.hoverIndex = Math.max(0, Math.min(rows.length - 1,
                chart.mode === "line" ? Math.round(ratio * (rows.length - 1))
                                      : Math.floor(ratio * rows.length)))
            chart.hoverX = mouse.x
        }
        onExited: chart.hoverIndex = -1
        onWheel: function(wheel) { wheel.accepted = false }
    }

    Rectangle {
        id: hoverTip
        visible: chart.hoverIndex >= 0 && chart.hoverText().length > 0
        x: Math.max(4, Math.min(chart.width - width - 4, chart.hoverX + 12))
        y: 20
        width: hoverLabel.implicitWidth + 18
        height: hoverLabel.implicitHeight + 14
        radius: 7
        color: chart.ui ? chart.ui.surface : "#FFFFFF"
        border.width: 1
        border.color: chart.ui ? chart.ui.border : "#DDE6EF"
        Text {
            id: hoverLabel
            anchors.centerIn: parent
            text: chart.hoverText()
            color: chart.ui ? chart.ui.text : "#172A40"
            font.family: chart.ui ? chart.ui.fontFamily : "Microsoft YaHei UI"
            font.pixelSize: 11
            lineHeight: 1.2
        }
    }

    Text {
        anchors.centerIn: parent
        visible: chart.validRows().length === 0
        text: chart.emptyText
        color: chart.ui ? chart.ui.faint : "#8A9AAF"
        font.family: chart.ui ? chart.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 13
    }
}
