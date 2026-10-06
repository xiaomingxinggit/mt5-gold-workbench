import QtQuick
import QtQuick.Controls

RadioButton {
    id: control
    property var ui
    spacing: 8
    font.family: ui.fontFamily
    font.pixelSize: 14
    indicator: Rectangle {
        implicitWidth: 18; implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: width / 2
        color: control.ui.surface
        border.color: control.checked || control.activeFocus ? control.ui.accent : control.ui.muted
        border.width: 2
        opacity: control.enabled ? 1 : 0.45
        Rectangle {
            anchors.centerIn: parent
            width: 8; height: 8; radius: 4
            color: control.ui.accent
            visible: control.checked
        }
    }
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? control.ui.text : control.ui.muted
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
    }
}
