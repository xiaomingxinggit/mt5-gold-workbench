import QtQuick

Rectangle {
    id: control
    property var ui
    property string text: ""
    property string variant: "secondary"
    property string leading: ""
    property bool busy: false
    signal clicked()

    readonly property bool primary: variant === "primary"
    readonly property bool danger: variant === "danger"
    readonly property bool ghost: variant === "ghost"
    readonly property color ink: primary ? (ui ? ui.accentText : "#FFFFFF")
                                      : danger ? (ui ? ui.negative : "#C4475C")
                                               : (ui ? ui.text : "#172A40")

    implicitWidth: caption.implicitWidth + (leading ? 56 : 30)
    implicitHeight: 38
    radius: 9
    color: primary ? (ui ? ui.accent : "#087F73")
                   : mouse.containsMouse ? (ui ? ui.hover : "#F0F4F9")
                                         : ghost ? "transparent" : (ui ? ui.surfaceAlt : "#EDF2F8")
    border.width: primary || ghost ? 0 : 1
    border.color: danger ? (ui ? ui.negative : "#C4475C") : (ui ? ui.border : "#DDE6EF")
    opacity: enabled ? 1 : 0.45

    Row {
        anchors.centerIn: parent
        spacing: 7
        Text {
            visible: control.leading !== ""
            text: control.leading
            color: control.ink
            font.family: ui ? ui.fontFamily : "Microsoft YaHei UI"
            font.pixelSize: 15
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: caption
            text: control.busy ? "处理中…" : control.text
            color: control.ink
            font.family: ui ? ui.fontFamily : "Microsoft YaHei UI"
            font.pixelSize: 13
            font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (control.enabled && !control.busy) control.clicked()
    }
}
