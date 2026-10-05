import QtQuick

Flow {
    id: strip
    property var ui
    property var images: []
    signal removed(var image)
    signal imageClicked(int index)
    spacing: 8
    visible: images.length > 0
    Repeater {
        model: strip.images
        delegate: Rectangle {
            id: thumbnail
            required property var modelData
            required property int index
            width: Math.min(138, strip.width); height: 102; radius: 8
            color: strip.ui.surfaceAlt; border.color: strip.ui.border
            clip: true
            Image { anchors.fill: parent; anchors.margins: 3; source: thumbnail.modelData.url || ""; fillMode: Image.PreserveAspectCrop; autoTransform: true; asynchronous: true }
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 24; color: strip.ui.surface; opacity: 0.9 }
            Text { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 6; text: String(thumbnail.modelData.name || "图片"); color: strip.ui.text; font.family: strip.ui.fontFamily; font.pixelSize: 11; elide: Text.ElideMiddle }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: strip.imageClicked(thumbnail.index) }
            Rectangle {
                anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 5
                width: 23; height: 23; radius: 11
                color: strip.ui.surface; border.color: strip.ui.border
                Text { anchors.centerIn: parent; text: "×"; color: strip.ui.text; font.family: strip.ui.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: strip.removed(thumbnail.modelData) }
            }
        }
    }
}
