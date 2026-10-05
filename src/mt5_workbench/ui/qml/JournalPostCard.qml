import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

UiCard {
    id: card
    objectName: "journalTimelinePost"
    property var post
    property var journal
    readonly property int postId: Number(post.id)
    readonly property var replyImages: journal.value("replyDraftImages", {})[String(postId)] || []
    padding: 22
    spacing: 14

    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        Text { text: String(card.post.timeLabel || "—"); color: card.ui.text; font.family: card.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
        Item { Layout.fillWidth: true }
        UiButton { ui: card.ui; text: "删除"; variant: "ghost"; onClicked: card.journal.request("journalDelete", {postId: card.postId}) }
    }
    Text { Layout.fillWidth: true; visible: text.length > 0; text: String(card.post.body || ""); textFormat: Text.PlainText; color: card.ui.text; font.family: card.ui.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap }
    JournalImageStrip {
        ui: card.ui
        Layout.fillWidth: true
        sources: card.post.images || []
        onImageClicked: function(index) { card.journal.openImages(sources, index) }
    }
    Text { visible: !!card.post.positions && card.post.positions.length > 0; text: "关联持仓 · " + (card.post.positions ? card.post.positions.length : 0); color: card.ui.muted; font.family: card.ui.fontFamily; font.pixelSize: 12 }
    Repeater {
        model: card.post.positions || []
        delegate: Rectangle {
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: positionDetails.implicitHeight + 24
            radius: 8; color: card.ui.surfaceAlt
            ColumnLayout {
                id: positionDetails
                anchors.fill: parent; anchors.margins: 12
                spacing: 6
                Text { Layout.fillWidth: true; text: "#" + String(modelData.ticket || "—") + " · " + String(modelData.side || "—") + " " + String(modelData.symbol || "—") + " · " + String(modelData.volume || "—") + " lot"; color: card.ui.text; font.family: card.ui.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                Text { Layout.fillWidth: true; text: card.journal.positionResult(modelData); color: modelData.status === "closed" && Number(modelData.resultUsd) < 0 ? card.ui.negative : card.ui.positive; font.family: card.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap }
            }
        }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: card.ui.border }
    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        Text { text: "回复 · " + (card.post.replies || []).length; color: card.ui.muted; font.family: card.ui.fontFamily; font.pixelSize: 12 }
        Item { Layout.fillWidth: true }
        UiButton {
            objectName: "journalReplyToggle"
            ui: card.ui
            text: card.journal.replyingTo === card.postId ? "收起回复" : "写回复"
            variant: "ghost"
            enabled: card.journal.value("canPublish", false)
            onClicked: card.journal.replyingTo = card.journal.replyingTo === card.postId ? 0 : card.postId
        }
    }
    Repeater {
        model: card.post.replies || []
        delegate: UiCard {
            required property var modelData
            objectName: "journalReplyCard"
            ui: card.ui
            Layout.fillWidth: true
            padding: 14
            spacing: 8
            color: card.ui.surfaceAlt
            border.width: 0
            Text { text: String(modelData.dateLabel || "") + " " + String(modelData.timeLabel || ""); color: card.ui.muted; font.family: card.ui.fontFamily; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; visible: text.length > 0; text: String(modelData.body || ""); textFormat: Text.PlainText; color: card.ui.text; font.family: card.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
            JournalImageStrip {
                ui: card.ui
                Layout.fillWidth: true
                sources: modelData.images || []
                onImageClicked: function(index) { card.journal.openImages(sources, index) }
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: card.journal.replyingTo === card.postId
        spacing: 12
        TextArea {
            id: replyEditor
            objectName: "journalReplyEditor"
            Layout.fillWidth: true
            Layout.preferredHeight: 90
            text: card.journal.replyBody(card.postId)
            placeholderText: "补充后续观察或回复这篇日志…"
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            color: card.ui.text; placeholderTextColor: card.ui.muted
            font.family: card.ui.fontFamily; font.pixelSize: 14
            leftPadding: 13; rightPadding: 13; topPadding: 11; bottomPadding: 11
            onTextChanged: card.journal.updateReplyBody(card.postId, text)
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)
                        && card.journal.bridge && card.journal.bridge.hasJournalImageOnClipboard()) {
                    card.journal.request("journalPasteImage", {postId: card.postId})
                    event.accepted = true
                }
            }
            background: Rectangle { color: card.ui.surfaceAlt; radius: 9; border.color: replyEditor.activeFocus ? card.ui.accent : card.ui.border }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Text { text: "图片 " + card.replyImages.length + " / 4"; color: card.ui.muted; font.family: card.ui.fontFamily; font.pixelSize: 12 }
            UiButton { ui: card.ui; text: "粘贴图片"; onClicked: card.journal.request("journalPasteImage", {postId: card.postId}) }
            UiButton { ui: card.ui; text: "选择图片"; onClicked: card.journal.request("journalChooseImages", {postId: card.postId}) }
            Item { Layout.fillWidth: true }
            Text { text: card.journal.replyBody(card.postId).length + " / 2100"; color: card.journal.replyBody(card.postId).length > 2100 ? card.ui.negative : card.ui.muted; font.family: card.ui.fontFamily; font.pixelSize: 12 }
        }
        JournalDraftImages {
            ui: card.ui
            Layout.fillWidth: true
            images: card.replyImages
            onRemoved: function(image) { card.journal.request("journalRemoveImage", {postId: card.postId, path: image.path}) }
            onImageClicked: function(index) { card.journal.openImages(images.map(function(image) { return image.url }), index) }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Item { Layout.fillWidth: true }
            UiButton { ui: card.ui; text: "取消"; onClicked: card.journal.discardReply(card.postId) }
            UiButton {
                objectName: "journalReplyPublish"
                ui: card.ui; text: "发布回复"; variant: "primary"
                enabled: card.journal.value("canPublish", false)
                         && (card.journal.replyBody(card.postId).trim().length > 0 || card.replyImages.length > 0)
                         && card.journal.replyBody(card.postId).length <= 2100
                onClicked: card.journal.request("journalReplyPublish", {postId: card.postId, body: card.journal.replyBody(card.postId).trim()})
            }
        }
    }
}
