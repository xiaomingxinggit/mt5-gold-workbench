import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: viewer
    objectName: "journalImageViewer"
    property var ui
    property var sources: []
    property int currentIndex: 0
    property real zoom: 1

    function showImages(images, index) {
        if (!images || !images.length) return
        sources = images
        currentIndex = Math.max(0, Math.min(index, images.length - 1))
        zoom = 1
        open()
    }
    function changeImage(offset) {
        currentIndex = Math.max(0, Math.min(sources.length - 1, currentIndex + offset))
    }
    onCurrentIndexChanged: zoom = 1
    onZoomChanged: {
        imageViewport.contentX = Math.max(0, (imageViewport.contentWidth - imageViewport.width) / 2)
        imageViewport.contentY = Math.max(0, (imageViewport.contentHeight - imageViewport.height) / 2)
    }
    onClosed: { sources = []; zoom = 1 }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.max(0, Math.min(parent ? parent.width - 48 : 0, 1200))
    height: Math.max(0, Math.min(parent ? parent.height - 48 : 0, 900))
    padding: 22
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: viewer.ui.surface; radius: 15; border.color: viewer.ui.border }
    Overlay.modal: Rectangle { color: "#990C1420" }

    Shortcut { sequence: "Left"; enabled: viewer.opened && viewer.currentIndex > 0; onActivated: viewer.changeImage(-1) }
    Shortcut { sequence: "Right"; enabled: viewer.opened && viewer.currentIndex < viewer.sources.length - 1; onActivated: viewer.changeImage(1) }

    contentItem: ColumnLayout {
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Text { text: "查看图片"; color: viewer.ui.text; font.family: viewer.ui.fontFamily; font.pixelSize: 18; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Text { text: (viewer.currentIndex + 1) + " / " + viewer.sources.length; color: viewer.ui.muted; font.family: viewer.ui.fontFamily; font.pixelSize: 13 }
            UiButton { objectName: "journalPreviewClose"; ui: viewer.ui; text: "关闭"; onClicked: viewer.close() }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 9
            color: viewer.ui.surfaceAlt
            clip: true
            Flickable {
                id: imageViewport
                anchors.fill: parent
                anchors.margins: 12
                contentWidth: Math.max(width, previewImage.width)
                contentHeight: Math.max(height, previewImage.height)
                interactive: viewer.zoom > 1
                boundsBehavior: Flickable.StopAtBounds
                Image {
                    id: previewImage
                    objectName: "journalPreviewImage"
                    width: imageViewport.width * viewer.zoom
                    height: imageViewport.height * viewer.zoom
                    source: viewer.visible && viewer.sources.length ? String(viewer.sources[viewer.currentIndex]) : ""
                    fillMode: Image.PreserveAspectFit
                    autoTransform: true
                    asynchronous: true
                }
                ScrollBar.vertical: UiScrollBar { ui: viewer.ui }
                ScrollBar.horizontal: UiScrollBar { ui: viewer.ui }
            }
            Text {
                anchors.centerIn: parent
                visible: previewImage.status === Image.Loading || previewImage.status === Image.Error
                text: previewImage.status === Image.Error ? "图片无法读取，文件可能已被移动或删除。" : "正在加载图片…"
                color: viewer.ui.muted
                font.family: viewer.ui.fontFamily
                font.pixelSize: 14
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            UiButton { objectName: "journalPreviewPrevious"; ui: viewer.ui; text: "上一张"; enabled: viewer.currentIndex > 0; onClicked: viewer.changeImage(-1) }
            UiButton { objectName: "journalPreviewNext"; ui: viewer.ui; text: "下一张"; enabled: viewer.currentIndex < viewer.sources.length - 1; onClicked: viewer.changeImage(1) }
            Item { Layout.fillWidth: true }
            UiButton { ui: viewer.ui; text: "缩小"; enabled: viewer.zoom > 1; onClicked: viewer.zoom = Math.max(1, viewer.zoom - 0.5) }
            Text { text: Math.round(viewer.zoom * 100) + "%"; color: viewer.ui.muted; font.family: viewer.ui.fontFamily; font.pixelSize: 13; Layout.preferredWidth: 44; horizontalAlignment: Text.AlignHCenter }
            UiButton { objectName: "journalPreviewZoomIn"; ui: viewer.ui; text: "放大"; enabled: viewer.zoom < 4; onClicked: viewer.zoom = Math.min(4, viewer.zoom + 0.5) }
            UiButton { ui: viewer.ui; text: "适应窗口"; enabled: viewer.zoom !== 1; onClicked: viewer.zoom = 1 }
        }
        Text { text: "放大后可拖动查看；左右方向键切换图片，按 Esc 关闭。"; color: viewer.ui.muted; font.family: viewer.ui.fontFamily; font.pixelSize: 12 }
    }
}
