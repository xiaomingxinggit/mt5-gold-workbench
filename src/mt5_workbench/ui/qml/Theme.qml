import QtQuick

QtObject {
    id: theme

    property bool dark: false
    property int timeOffsetMinutes: 480
    property string timeZoneLabel: "UTC+08:00"
    property bool followSystemTime: false

    function dateParts(value) {
        if (!value) return ""
        const date = new Date(String(value))
        if (!isFinite(date.getTime())) return ""
        const offset = followSystemTime ? -date.getTimezoneOffset() : timeOffsetMinutes
        return new Date(date.getTime() + offset * 60000).toISOString()
    }
    function formatTime(value, timeOnly) {
        const parts = dateParts(value)
        if (!parts) return value ? String(value) : "—"
        return timeOnly ? parts.slice(11, 16) : parts.slice(0, 19).replace("T", " ")
    }
    function dateKey(value) { return dateParts(value).slice(0, 10) }
    function dateLabel(value) {
        const parts = dateParts(value)
        return parts ? Number(parts.slice(0, 4)) + "年" + Number(parts.slice(5, 7)) + "月" + Number(parts.slice(8, 10)) + "日" : "日期未知"
    }
    readonly property string fontFamily: "Microsoft YaHei UI"

    readonly property color bg: dark ? "#0C1420" : "#F4F7FB"
    readonly property color sidebar: dark ? "#111D2D" : "#FFFFFF"
    readonly property color surface: dark ? "#172438" : "#FFFFFF"
    readonly property color surfaceAlt: dark ? "#1D2E45" : "#EDF2F8"
    readonly property color border: dark ? "#2B4057" : "#DDE6EF"
    readonly property color text: dark ? "#F3F7FB" : "#172A40"
    readonly property color muted: dark ? "#9BAFC3" : "#60758D"
    readonly property color faint: dark ? "#6D839A" : "#8A9AAF"
    readonly property color accent: dark ? "#62D5C3" : "#087F73"
    readonly property color accentSoft: dark ? "#183C43" : "#DDF4EF"
    readonly property color accentText: dark ? "#0B2530" : "#FFFFFF"
    readonly property color positive: dark ? "#62D5C3" : "#087F73"
    readonly property color negative: dark ? "#FF8D9C" : "#C4475C"
    readonly property color warning: dark ? "#F6C777" : "#A66817"
    readonly property color chartBlue: dark ? "#90BCFF" : "#4675B3"
    readonly property color chartGrid: dark ? "#30445A" : "#E3EAF2"
    readonly property color chartDown: dark ? "#FF8D9C" : "#D9576B"
    readonly property color chartUp: dark ? "#62D5C3" : "#0A9D8D"
    readonly property color hover: dark ? "#263A51" : "#F0F4F9"
    readonly property color navActive: dark ? "#204548" : "#E0F4EF"
}
