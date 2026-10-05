import QtQuick

Flow {
    id: strip
    property var ui
    property var sources: []
    signal imageClicked(int index)
    spacing: 8
    visible: sources.length > 0
    Repeater {
        model: strip.sources
        delegate: Rectangle {
            required property var modelData
            required property int index
            objectName: "journalImageThumbnail"
            width: Math.min(160, strip.width)
            height: 112
            radius: 8
            color: strip.ui.surfaceAlt
            border.color: imageMouse.containsMouse ? strip.ui.accent : strip.ui.border
            clip: true
            Image { anchors.fill: parent; anchors.margins: 2; source: String(modelData); fillMode: Image.PreserveAspectCrop; autoTransform: true; asynchronous: true }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                height: 24
                color: strip.ui.surface
                opacity: 0.9
                visible: imageMouse.containsMouse
                Text { anchors.centerIn: parent; text: "点击查看"; color: strip.ui.text; font.family: strip.ui.fontFamily; font.pixelSize: 11 }
            }
            MouseArea { id: imageMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: strip.imageClicked(index) }
        }
    }
}
