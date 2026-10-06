import QtQuick
import QtQuick.Controls

ToolTip {
    id: control
    property var ui
    font.family: ui.fontFamily
    font.pixelSize: 12
    contentItem: Text { text: control.text; font: control.font; color: control.ui.text }
    background: Rectangle { radius: 7; color: control.ui.surfaceAlt; border.color: control.ui.border }
}
