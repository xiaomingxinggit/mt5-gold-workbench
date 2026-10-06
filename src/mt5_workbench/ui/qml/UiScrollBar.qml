import QtQuick
import QtQuick.Controls

ScrollBar {
    id: control
    property var ui
    // ScrollView's replacement bars need explicit edge geometry.
    anchors.right: orientation === Qt.Vertical && parent ? parent.right : undefined
    anchors.bottom: orientation === Qt.Horizontal && parent ? parent.bottom : undefined
    width: orientation === Qt.Horizontal && parent ? parent.width : implicitWidth
    height: orientation === Qt.Vertical && parent ? parent.height : implicitHeight
    padding: 2
    minimumSize: 0.06
    contentItem: Rectangle {
        implicitWidth: 8
        implicitHeight: 8
        radius: 4
        color: control.pressed || control.hovered ? control.ui.muted : control.ui.faint
        opacity: control.size < 1 ? 0.7 : 0
    }
    background: Rectangle { color: "transparent" }
}
