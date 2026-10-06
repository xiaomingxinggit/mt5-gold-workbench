import QtQuick
import QtQuick.Controls

CheckBox {
    id: control
    property var ui
    spacing: 8
    font.family: ui ? ui.fontFamily : "Microsoft YaHei UI"
    font.pixelSize: 13
    indicator: Rectangle {
        implicitWidth: 18; implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 4
        color: control.checkState !== Qt.Unchecked ? control.ui.accent : control.ui.surface
        border.color: control.activeFocus || control.checkState !== Qt.Unchecked ? control.ui.accent : control.ui.muted
        opacity: control.enabled ? 1 : 0.45
        Text {
            anchors.centerIn: parent
            text: control.checkState === Qt.PartiallyChecked ? "−" : "✓"
            visible: control.checkState !== Qt.Unchecked
            color: control.ui.accentText
            font.family: control.font.family; font.pixelSize: 13; font.weight: Font.DemiBold
        }
    }
    contentItem: Text {
        text: control.text
        font: control.font; color: control.ui.text
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
    }
}
